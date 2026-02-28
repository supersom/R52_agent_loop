import json
import os


TEXT_EDIT_OPS = {
    "replace_snippet",
    "delete_snippet",
    "insert_before",
    "insert_after",
    "append_text",
    "prepend_text",
    "replace_entire_file",
}
MISSING = object()


def parse_edit_instructions(response_text: str) -> tuple[list[dict], bool]:
    """
    Parse structured incremental edit instructions from an LLM response.

    Returns:
    - list of edit operation dictionaries
    - bool indicating whether non-JSON text had to be stripped first
    """
    stripped = response_text.strip()
    sanitized = False

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        json_blob = _extract_first_json_object(stripped)
        if json_blob is None:
            raise ValueError("Response is not valid JSON edit instructions")
        sanitized = json_blob != stripped
        try:
            payload = json.loads(json_blob)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON edit instructions: {e}") from e

    if not isinstance(payload, dict):
        raise ValueError("JSON edit instructions must be an object")

    edits = payload.get("edits")
    if not isinstance(edits, list) or not edits:
        raise ValueError("JSON edit instructions must include a non-empty 'edits' list")

    for idx, edit in enumerate(edits, start=1):
        if not isinstance(edit, dict):
            raise ValueError(f"Edit #{idx} is not an object")
        op = edit.get("op")
        if not isinstance(op, str) or not op:
            raise ValueError(f"Edit #{idx} is missing required string field 'op'")

    return edits, sanitized


def apply_edit_instructions(original_text: str, edits: list[dict]) -> str:
    """
    Deterministically apply a sequence of single-file edit operations.

    Supported operations:
    - replace_snippet: {"op":"replace_snippet","old":"...","new":"...","occurrence":1}
    - delete_snippet: {"op":"delete_snippet","old":"...","occurrence":1}
    - insert_before: {"op":"insert_before","anchor":"...","text":"...","occurrence":1}
    - insert_after: {"op":"insert_after","anchor":"...","text":"...","occurrence":1}
    - append_text: {"op":"append_text","text":"..."}
    - prepend_text: {"op":"prepend_text","text":"..."}
    - replace_entire_file: {"op":"replace_entire_file","content":"..."}
    """
    updated = original_text
    for idx, edit in enumerate(edits, start=1):
        updated = _apply_text_edit(updated, edit, idx)

    return updated


def apply_workspace_edit_instructions(
    workspace_dir: str,
    edits: list[dict],
    *,
    default_path: str | None = None,
) -> list[str]:
    """
    Apply path-aware edit operations to files under workspace_dir atomically.

    Supported file operations:
    - create_file: {"op":"create_file","path":"dir/file","content":"..."}
    - delete_file: {"op":"delete_file","path":"dir/file"}
    - move_file: {"op":"move_file","path":"old/file","new_path":"new/file"}

    Text edit operations are the same as apply_edit_instructions, and may
    additionally include "path". If omitted, default_path is used.

    Returns a sorted list of relative paths changed by the operation set.
    Raises ValueError on validation or apply failures and does not write any
    changes to disk in that case.
    """
    if not os.path.isdir(workspace_dir):
        raise ValueError(f"Workspace directory does not exist: {workspace_dir}")

    workspace_abs = os.path.abspath(workspace_dir)
    default_rel = (
        _normalize_relative_path(default_path, idx=0, field="default_path")
        if default_path is not None
        else None
    )

    file_cache: dict[str, str | object] = {}
    dirty_paths: set[str] = set()

    def load_file(rel_path: str, idx: int) -> str | object:
        if rel_path in file_cache:
            return file_cache[rel_path]
        abs_path = _absolute_workspace_path(workspace_abs, rel_path, idx=idx, field="path")
        if os.path.isdir(abs_path):
            raise ValueError(f"Edit #{idx}: path points to a directory, not a file: {rel_path}")
        if os.path.exists(abs_path):
            try:
                with open(abs_path, "r") as f:
                    file_cache[rel_path] = f.read()
            except OSError as e:
                raise ValueError(f"Edit #{idx}: failed to read '{rel_path}': {e}") from e
        else:
            file_cache[rel_path] = MISSING
        return file_cache[rel_path]

    for idx, edit in enumerate(edits, start=1):
        op = edit["op"]

        if op in TEXT_EDIT_OPS:
            target_rel = _resolve_target_path(edit, idx=idx, default_rel=default_rel)
            current_value = load_file(target_rel, idx)
            if current_value is MISSING:
                raise ValueError(f"Edit #{idx}: target file not found: {target_rel}")
            assert isinstance(current_value, str)
            updated_value = _apply_text_edit(current_value, edit, idx)
            file_cache[target_rel] = updated_value
            dirty_paths.add(target_rel)
            continue

        if op == "create_file":
            target_rel = _required_path(edit, "path", idx)
            current_value = load_file(target_rel, idx)
            if current_value is not MISSING:
                raise ValueError(f"Edit #{idx}: create_file target already exists: {target_rel}")
            content = _required_string(edit, "content", idx)
            file_cache[target_rel] = content
            dirty_paths.add(target_rel)
            continue

        if op == "delete_file":
            target_rel = _required_path(edit, "path", idx)
            current_value = load_file(target_rel, idx)
            if current_value is MISSING:
                raise ValueError(f"Edit #{idx}: delete_file target not found: {target_rel}")
            file_cache[target_rel] = MISSING
            dirty_paths.add(target_rel)
            continue

        if op == "move_file":
            source_rel = _resolve_target_path(edit, idx=idx, default_rel=default_rel)
            destination_rel = _required_path(edit, "new_path", idx)
            if source_rel == destination_rel:
                raise ValueError(f"Edit #{idx}: move_file source and destination are the same: {source_rel}")
            source_value = load_file(source_rel, idx)
            if source_value is MISSING:
                raise ValueError(f"Edit #{idx}: move_file source not found: {source_rel}")
            destination_value = load_file(destination_rel, idx)
            if destination_value is not MISSING:
                raise ValueError(f"Edit #{idx}: move_file destination already exists: {destination_rel}")
            file_cache[destination_rel] = source_value
            file_cache[source_rel] = MISSING
            dirty_paths.add(source_rel)
            dirty_paths.add(destination_rel)
            continue

        raise ValueError(f"Edit #{idx}: unsupported operation '{op}'")

    for rel_path in sorted(dirty_paths):
        abs_path = _absolute_workspace_path(workspace_abs, rel_path, idx=0, field="path")
        value = file_cache[rel_path]
        if value is MISSING:
            if os.path.exists(abs_path):
                try:
                    os.remove(abs_path)
                except OSError as e:
                    raise ValueError(f"Failed to delete '{rel_path}': {e}") from e
            continue

        assert isinstance(value, str)
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.isdir(abs_path):
            raise ValueError(f"Cannot write file because a directory exists at '{rel_path}'")
        try:
            with open(abs_path, "w") as f:
                f.write(value)
        except OSError as e:
            raise ValueError(f"Failed to write '{rel_path}': {e}") from e

    return sorted(dirty_paths)


def _extract_first_json_object(text: str) -> str | None:
    in_string = False
    escaped = False
    depth = 0
    start_idx = -1

    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            if depth == 0:
                start_idx = i
            depth += 1
            continue
        if ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start_idx >= 0:
                return text[start_idx:i + 1]

    return None


def _required_string(edit: dict, key: str, idx: int) -> str:
    value = edit.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Edit #{idx}: field '{key}' must be a string")
    return value


def _required_path(edit: dict, key: str, idx: int) -> str:
    value = edit.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Edit #{idx}: field '{key}' must be a string")
    return _normalize_relative_path(value, idx=idx, field=key)


def _occurrence(edit: dict, idx: int) -> int | None:
    value = edit.get("occurrence")
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Edit #{idx}: optional field 'occurrence' must be a positive integer")
    return value


def _normalize_relative_path(path: str, *, idx: int, field: str) -> str:
    raw = path.strip()
    if not raw:
        raise ValueError(f"Edit #{idx}: field '{field}' cannot be empty")

    normalized = os.path.normpath(raw)
    if os.path.isabs(normalized):
        raise ValueError(f"Edit #{idx}: field '{field}' must be a relative path: {raw}")
    if normalized in (".", "..") or normalized.startswith(f"..{os.sep}"):
        raise ValueError(f"Edit #{idx}: field '{field}' escapes workspace: {raw}")
    return normalized


def _absolute_workspace_path(workspace_abs: str, rel_path: str, *, idx: int, field: str) -> str:
    abs_path = os.path.abspath(os.path.join(workspace_abs, rel_path))
    if os.path.commonpath([workspace_abs, abs_path]) != workspace_abs:
        raise ValueError(f"Edit #{idx}: field '{field}' escapes workspace: {rel_path}")
    return abs_path


def _resolve_target_path(edit: dict, *, idx: int, default_rel: str | None) -> str:
    path_value = edit.get("path")
    if path_value is None:
        if default_rel is None:
            raise ValueError(
                f"Edit #{idx}: missing required field 'path' for multi-file edit instructions"
            )
        return default_rel
    if not isinstance(path_value, str):
        raise ValueError(f"Edit #{idx}: field 'path' must be a string")
    return _normalize_relative_path(path_value, idx=idx, field="path")


def _find_occurrence(haystack: str, needle: str, occurrence: int | None, idx: int, field: str) -> int:
    if not needle:
        raise ValueError(f"Edit #{idx}: field '{field}' cannot be empty")

    positions: list[int] = []
    start = 0
    while True:
        pos = haystack.find(needle, start)
        if pos < 0:
            break
        positions.append(pos)
        start = pos + 1

    if not positions:
        raise ValueError(f"Edit #{idx}: '{field}' snippet not found in current source")

    if occurrence is None:
        if len(positions) > 1:
            raise ValueError(
                f"Edit #{idx}: '{field}' snippet matched {len(positions)} locations; set 'occurrence' to disambiguate"
            )
        return positions[0]

    if occurrence > len(positions):
        raise ValueError(
            f"Edit #{idx}: occurrence {occurrence} out of range for '{field}' snippet "
            f"(found {len(positions)} matches)"
        )
    return positions[occurrence - 1]


def _apply_text_edit(text: str, edit: dict, idx: int) -> str:
    op = edit["op"]
    try:
        if op == "replace_snippet":
            old = _required_string(edit, "old", idx)
            new = _required_string(edit, "new", idx)
            occurrence = _occurrence(edit, idx)
            return _replace_once(text, old, new, occurrence, idx)
        if op == "delete_snippet":
            old = _required_string(edit, "old", idx)
            occurrence = _occurrence(edit, idx)
            return _replace_once(text, old, "", occurrence, idx)
        if op == "insert_before":
            anchor = _required_string(edit, "anchor", idx)
            insert_text = _required_string(edit, "text", idx)
            occurrence = _occurrence(edit, idx)
            return _insert_relative(text, anchor, insert_text, before=True, occurrence=occurrence, idx=idx)
        if op == "insert_after":
            anchor = _required_string(edit, "anchor", idx)
            insert_text = _required_string(edit, "text", idx)
            occurrence = _occurrence(edit, idx)
            return _insert_relative(text, anchor, insert_text, before=False, occurrence=occurrence, idx=idx)
        if op == "append_text":
            append_text = _required_string(edit, "text", idx)
            return text + append_text
        if op == "prepend_text":
            prepend_text = _required_string(edit, "text", idx)
            return prepend_text + text
        if op == "replace_entire_file":
            return _required_string(edit, "content", idx)
        raise ValueError(f"Edit #{idx}: unsupported operation '{op}'")
    except ValueError as e:
        raise ValueError(str(e)) from e


def _replace_once(haystack: str, old: str, new: str, occurrence: int | None, idx: int) -> str:
    pos = _find_occurrence(haystack, old, occurrence, idx, "old")
    return haystack[:pos] + new + haystack[pos + len(old):]


def _insert_relative(
    haystack: str,
    anchor: str,
    text: str,
    *,
    before: bool,
    occurrence: int | None,
    idx: int,
) -> str:
    pos = _find_occurrence(haystack, anchor, occurrence, idx, "anchor")
    if before:
        return haystack[:pos] + text + haystack[pos:]
    return haystack[:pos + len(anchor)] + text + haystack[pos + len(anchor):]
