import os
import re


IGNORED_DIRS = {
    ".git",
    ".agent_loop",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".venv",
    "venv",
}

IGNORED_EXTENSIONS = {
    ".pyc",
    ".o",
    ".obj",
    ".so",
    ".dll",
    ".dylib",
    ".a",
    ".class",
    ".jar",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".pdf",
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "json",
    "code",
    "file",
    "files",
    "edit",
    "edits",
    "fix",
    "retry",
    "failed",
    "failure",
    "error",
    "output",
    "build",
    "test",
    "command",
}


def build_repo_attempt_context(
    *,
    repo_dir: str,
    entry_file_rel: str,
    query_text: str,
    max_files: int = 8,
    max_file_chars: int = 2500,
    max_total_chars: int = 14000,
    max_tree_lines: int = 180,
) -> tuple[str, list[str]]:
    """
    Build a compact repo context block and return (context_text, selected_files).
    """
    repo_abs = os.path.abspath(repo_dir)
    if not os.path.isdir(repo_abs):
        raise ValueError(f"Repo directory does not exist: {repo_dir}")

    entry_rel = _normalize_relpath(entry_file_rel)
    keywords = _extract_keywords(query_text)
    tree_text, all_files = _build_repo_tree(repo_abs, max_lines=max_tree_lines)
    selected_files = _select_files(
        all_files=all_files,
        entry_file_rel=entry_rel,
        keywords=keywords,
        max_files=max_files,
    )

    snippet_budget = max_total_chars
    snippets: list[str] = []
    kept_files: list[str] = []
    for rel_path in selected_files:
        abs_path = os.path.join(repo_abs, rel_path)
        content = _read_text_file(abs_path, max_chars=max_file_chars)
        if content is None:
            continue
        block = (
            f"--- File: {rel_path} ---\n"
            "```\n"
            f"{content}\n"
            "```\n"
        )
        if len(block) > snippet_budget and kept_files:
            break
        if len(block) > snippet_budget:
            # Keep at least one file, truncated.
            block = block[:snippet_budget]
        snippets.append(block)
        kept_files.append(rel_path)
        snippet_budget -= len(block)
        if snippet_budget <= 0:
            break

    context_text = (
        "=== REPO CONTEXT (selected, compact) ===\n"
        f"Entry file: {entry_rel}\n"
        f"Keywords: {', '.join(sorted(keywords)) if keywords else '(none)'}\n\n"
        "Repo tree:\n"
        f"{tree_text}\n\n"
        "Selected file snippets:\n"
        f"{''.join(snippets)}"
        "=======================================\n"
    )
    return context_text, kept_files


def _normalize_relpath(path: str) -> str:
    normalized = os.path.normpath(path.strip())
    if not normalized or normalized in (".", "..") or os.path.isabs(normalized):
        raise ValueError(f"Invalid relative entry path: {path}")
    if normalized.startswith(f"..{os.sep}"):
        raise ValueError(f"Entry path escapes repo root: {path}")
    return normalized


def _extract_keywords(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    return {w for w in words if w not in STOPWORDS}


def _build_repo_tree(repo_abs: str, *, max_lines: int) -> tuple[str, list[str]]:
    lines: list[str] = []
    files: list[str] = []

    for root, dirs, filenames in os.walk(repo_abs):
        dirs[:] = sorted([d for d in dirs if d not in IGNORED_DIRS])
        rel_root = os.path.relpath(root, repo_abs)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        indent = "  " * depth

        if rel_root == ".":
            lines.append(".")
        else:
            lines.append(f"{indent}{os.path.basename(root)}/")
        if len(lines) >= max_lines:
            lines.append("  ... (truncated)")
            break

        for file_name in sorted(filenames):
            ext = os.path.splitext(file_name)[1].lower()
            if ext in IGNORED_EXTENSIONS:
                continue
            rel_path = file_name if rel_root == "." else os.path.join(rel_root, file_name)
            files.append(rel_path)
            lines.append(f"{indent}  {file_name}")
            if len(lines) >= max_lines:
                lines.append("  ... (truncated)")
                break
        if len(lines) >= max_lines:
            break

    return "\n".join(lines), files


def _select_files(
    *,
    all_files: list[str],
    entry_file_rel: str,
    keywords: set[str],
    max_files: int,
) -> list[str]:
    if not all_files:
        return []

    scored: list[tuple[int, str]] = []
    key_list = sorted(keywords)
    for rel_path in all_files:
        score = 0
        path_l = rel_path.lower()
        base_l = os.path.basename(path_l)
        if rel_path == entry_file_rel:
            score += 1000
        if base_l.startswith("test_") or "/tests/" in f"/{path_l}/":
            score += 5
        for key in key_list:
            if key in path_l:
                score += 8
        scored.append((score, rel_path))

    scored.sort(key=lambda x: (-x[0], x[1]))
    selected = [p for _, p in scored[:max_files]]

    # Ensure entry file is present whenever available.
    if entry_file_rel in all_files and entry_file_rel not in selected:
        if selected:
            selected[-1] = entry_file_rel
        else:
            selected.append(entry_file_rel)

    # Keep deterministic unique order.
    seen: set[str] = set()
    deduped: list[str] = []
    for path in selected:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped[:max_files]


def _read_text_file(path: str, *, max_chars: int) -> str | None:
    try:
        with open(path, "rb") as f:
            raw = f.read(max_chars + 1)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n... (truncated)"
    return text
