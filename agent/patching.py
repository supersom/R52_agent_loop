import re


def apply_unified_diff_patch(original_text: str, patch_text: str) -> str:
    """
    Apply a single-file unified diff patch to text and return the patched result.
    """
    fuzzy_window = 5
    patch_lines = patch_text.splitlines(keepends=True)
    hunk_start = next((i for i, line in enumerate(patch_lines) if line.startswith("@@")), None)
    if hunk_start is None:
        raise ValueError("No unified diff hunk found in LLM response")

    patch_lines = patch_lines[hunk_start:]
    original_lines = original_text.splitlines(keepends=True)
    output_lines = []
    orig_idx = 0
    i = 0

    hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    while i < len(patch_lines):
        header = patch_lines[i]
        if not header.startswith("@@"):
            raise ValueError(f"Unexpected patch content outside hunk: {header.rstrip()}")

        match = hunk_re.match(header)
        if not match:
            raise ValueError(f"Malformed unified diff hunk header: {header.rstrip()}")

        start_old = int(match.group(1))
        target_orig_idx = max(start_old - 1, 0)
        hunk_begin = i
        i += 1
        while i < len(patch_lines) and not patch_lines[i].startswith("@@"):
            i += 1
        hunk_body = patch_lines[hunk_begin + 1:i]

        expected_old_lines = []
        for line in hunk_body:
            if line.startswith("\\ No newline at end of file"):
                continue
            if not line:
                continue
            if line[0] in (" ", "-"):
                expected_old_lines.append(line[1:])

        def old_lines_match_at(start_idx: int) -> bool:
            probe_idx = start_idx
            for expected_line in expected_old_lines:
                if probe_idx >= len(original_lines) or original_lines[probe_idx] != expected_line:
                    return False
                probe_idx += 1
            return True

        candidate_orig_idx = None
        preferred = max(target_orig_idx, orig_idx)
        if old_lines_match_at(preferred):
            candidate_orig_idx = preferred
        else:
            min_idx = max(orig_idx, target_orig_idx - fuzzy_window)
            max_idx = min(len(original_lines), target_orig_idx + fuzzy_window)
            offsets = [0]
            for off in range(1, fuzzy_window + 1):
                offsets.extend([-off, off])
            for off in offsets:
                idx = target_orig_idx + off
                if idx < min_idx or idx > max_idx:
                    continue
                if idx < orig_idx:
                    continue
                if old_lines_match_at(idx):
                    candidate_orig_idx = idx
                    if idx != target_orig_idx:
                        print(
                            f"[Patch] Fuzzy-aligned hunk from old line {start_old} "
                            f"to source line {idx + 1}."
                        )
                    break

        if candidate_orig_idx is None:
            raise ValueError("Patch context does not match current source")

        output_lines.extend(original_lines[orig_idx:candidate_orig_idx])
        orig_idx = candidate_orig_idx
        hunk_idx = 0

        while hunk_idx < len(hunk_body):
            line = hunk_body[hunk_idx]
            if line.startswith("\\ No newline at end of file"):
                hunk_idx += 1
                continue
            if not line:
                raise ValueError("Empty patch line in hunk")
            op = line[0]
            text = line[1:]
            if op == " ":
                if orig_idx >= len(original_lines) or original_lines[orig_idx] != text:
                    raise ValueError("Patch context does not match current source")
                output_lines.append(original_lines[orig_idx])
                orig_idx += 1
            elif op == "-":
                if orig_idx >= len(original_lines) or original_lines[orig_idx] != text:
                    raise ValueError("Patch deletion does not match current source")
                orig_idx += 1
            elif op == "+":
                output_lines.append(text)
            else:
                raise ValueError(f"Unsupported patch line prefix: {op}")
            hunk_idx += 1

    output_lines.extend(original_lines[orig_idx:])
    return "".join(output_lines)
