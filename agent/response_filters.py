import re


def sanitize_unified_diff_patch_text(patch_text: str, original_text: str | None = None) -> str:
    """
    Keep only the unified diff portion of a patch response and drop trailing
    non-diff noise (for example, leaked tool logs on stdout).
    Also tolerate an EOF newline mismatch when the current source has no trailing
    newline but the retained patch context line does (common when we truncate
    leaked stdout after an otherwise valid patch).
    """

    def normalize_eof_newline_mismatch(sanitized_patch: str) -> str:
        if original_text is None or original_text.endswith("\n"):
            return sanitized_patch
        if "\\ No newline at end of file" in sanitized_patch:
            return sanitized_patch

        lines = sanitized_patch.splitlines(keepends=True)
        if not lines:
            return sanitized_patch

        for idx in range(len(lines) - 1, -1, -1):
            line = lines[idx]
            if line.startswith("@@"):
                break
            if line.startswith((" ", "+", "-")) and line.endswith("\n"):
                lines[idx] = line[:-1]
                return "".join(lines)

        return sanitized_patch

    patch_lines = patch_text.splitlines(keepends=True)
    first_hunk_idx = next((i for i, line in enumerate(patch_lines) if line.startswith("@@")), None)
    if first_hunk_idx is None:
        return patch_text

    sanitized_end = first_hunk_idx
    i = first_hunk_idx
    while i < len(patch_lines):
        line = patch_lines[i]
        if line.startswith("@@"):
            sanitized_end = i + 1
            i += 1
            while i < len(patch_lines):
                hunk_line = patch_lines[i]
                if hunk_line.startswith("@@"):
                    break
                if hunk_line.startswith((" ", "+", "-", "\\ No newline at end of file")):
                    sanitized_end = i + 1
                    i += 1
                    continue
                return normalize_eof_newline_mismatch("".join(patch_lines[:sanitized_end]))
            continue
        i += 1

    if sanitized_end > first_hunk_idx:
        return normalize_eof_newline_mismatch("".join(patch_lines[:sanitized_end]))
    return patch_text


def sanitize_full_source_text(source_text: str) -> str:
    """
    Strip known leaked CLI/debug log lines from the end of a full-source response.
    Keep this conservative so we do not remove legitimate code.
    """
    noise_prefixes = (
        "ClearcutLogger:",
    )
    lines = source_text.splitlines(keepends=True)
    if not lines:
        return source_text

    removed_any = False
    while lines:
        line = lines[-1]
        if any(line.startswith(prefix) for prefix in noise_prefixes):
            lines.pop()
            removed_any = True
            continue
        break

    return "".join(lines) if removed_any else source_text


def extract_arm_asm_block(source_text: str) -> tuple[str, str | None]:
    """
    Trim leading non-assembly chatter before the first likely assembly block.
    Returns (trimmed_text, note_if_trimmed).
    """
    lines = source_text.splitlines(keepends=True)
    if not lines:
        return source_text, None

    directive_re = re.compile(r"^\s*\.[A-Za-z_][\w.]*\b")
    label_only_re = re.compile(r"^\s*(?:[A-Za-z_.$][\w.$]*|\d+):\s*(?:[@;].*)?$")
    label_prefix_re = re.compile(r"^\s*(?:[A-Za-z_.$][\w.$]*|\d+):\s*(.*)$")
    instr_re = re.compile(r"^\s*[A-Za-z][A-Za-z0-9_.]*\b(?:\s+.*)?$")

    def looks_asm_line(raw: str) -> bool:
        stripped = raw.strip()
        if not stripped:
            return False
        if stripped.startswith(("@", ";", "//", "/*", "*", "*/")):
            return True
        if directive_re.match(raw) or label_only_re.match(raw):
            return True
        label_prefix = label_prefix_re.match(raw)
        if label_prefix:
            tail = label_prefix.group(1).strip()
            if not tail:
                return True
            if tail.startswith(("@", ";", "//", "/*", "*", "*/")):
                return True
            return bool(directive_re.match(tail) or instr_re.match(tail))
        return bool(instr_re.match(raw))

    for i in range(len(lines)):
        if not looks_asm_line(lines[i]):
            continue
        window = lines[i:min(i + 8, len(lines))]
        asm_count = sum(1 for line in window if looks_asm_line(line))
        if asm_count >= 3:
            if i == 0:
                return source_text, None
            return "".join(lines[i:]), f"Trimmed {i} leading non-assembly line(s)"

    return source_text, None


def validate_arm_asm_source_text(source_text: str) -> str | None:
    """
    Return an error string if the text contains obvious non-assembly/prose content.
    This is a conservative fail-closed guard before writing agent_code.s.
    """
    directive_re = re.compile(r"^\s*\.[A-Za-z_][\w.]*\b")
    label_only_re = re.compile(r"^\s*(?:[A-Za-z_.$][\w.$]*|\d+):\s*(?:[@;].*)?$")
    label_prefix_re = re.compile(r"^\s*(?:[A-Za-z_.$][\w.$]*|\d+):\s*(.*)$")
    preproc_re = re.compile(r"^\s*#(?:include|define|if|ifdef|ifndef|elif|else|endif|pragma|error|warning)\b")
    instr_re = re.compile(r"^\s*[A-Za-z][A-Za-z0-9_.]*\b(?:\s+.*)?$")

    reject_prefixes = (
        "ClearcutLogger:",
        "Info:",
        "Warning:",
        "Error:",
        "I will ",
        "I'll ",
        "Let me ",
        "Here is ",
        "```",
        "# ",
        "##",
    )

    saw_asm_like = False
    for lineno, raw_line in enumerate(source_text.splitlines(), 1):
        line = raw_line.rstrip("\r")
        stripped = line.strip()
        if not stripped:
            continue

        if any(stripped.startswith(prefix) for prefix in reject_prefixes):
            return f"Line {lineno} looks like prose/log output, not assembly: {stripped}"

        if "`" in stripped:
            return f"Line {lineno} contains markdown/backticks, not assembly: {stripped}"

        if stripped.startswith(("@", ";", "//", "/*", "*", "*/")):
            continue

        if preproc_re.match(line) or directive_re.match(line) or label_only_re.match(line):
            saw_asm_like = True
            continue

        label_prefix = label_prefix_re.match(line)
        if label_prefix:
            tail = label_prefix.group(1).strip()
            if not tail:
                saw_asm_like = True
                continue
            if tail.startswith(("@", ";", "//", "/*", "*", "*/")):
                saw_asm_like = True
                continue
            if preproc_re.match(tail) or directive_re.match(tail) or instr_re.match(tail):
                saw_asm_like = True
                continue
            return f"Line {lineno} has a valid label but invalid code after ':': {tail}"

        # Allow mnemonics, macro invocations, and assembler pseudo-ops without leading dot.
        if instr_re.match(line):
            # Common prose signatures that still match the generic instruction regex.
            token = stripped.split(None, 1)[0].lower()
            if token in {"i", "here", "please", "note", "first", "then"}:
                return f"Line {lineno} looks like prose, not assembly: {stripped}"
            saw_asm_like = True
            continue

        return f"Line {lineno} is not recognized as ARM assembly syntax: {stripped}"

    if not saw_asm_like:
        return "No assembly-like directives, labels, or instructions found in generated source"
    return None
