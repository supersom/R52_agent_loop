import json


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
        op = edit["op"]
        try:
            if op == "replace_snippet":
                old = _required_string(edit, "old", idx)
                new = _required_string(edit, "new", idx)
                occurrence = _occurrence(edit, idx)
                updated = _replace_once(updated, old, new, occurrence, idx)
            elif op == "delete_snippet":
                old = _required_string(edit, "old", idx)
                occurrence = _occurrence(edit, idx)
                updated = _replace_once(updated, old, "", occurrence, idx)
            elif op == "insert_before":
                anchor = _required_string(edit, "anchor", idx)
                text = _required_string(edit, "text", idx)
                occurrence = _occurrence(edit, idx)
                updated = _insert_relative(updated, anchor, text, before=True, occurrence=occurrence, idx=idx)
            elif op == "insert_after":
                anchor = _required_string(edit, "anchor", idx)
                text = _required_string(edit, "text", idx)
                occurrence = _occurrence(edit, idx)
                updated = _insert_relative(updated, anchor, text, before=False, occurrence=occurrence, idx=idx)
            elif op == "append_text":
                text = _required_string(edit, "text", idx)
                updated = updated + text
            elif op == "prepend_text":
                text = _required_string(edit, "text", idx)
                updated = text + updated
            elif op == "replace_entire_file":
                content = _required_string(edit, "content", idx)
                updated = content
            else:
                raise ValueError(f"Edit #{idx}: unsupported operation '{op}'")
        except ValueError as e:
            raise ValueError(str(e)) from e

    return updated


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


def _occurrence(edit: dict, idx: int) -> int | None:
    value = edit.get("occurrence")
    if value is None:
        return None
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"Edit #{idx}: optional field 'occurrence' must be a positive integer")
    return value


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
