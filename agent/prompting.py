import os

from agent.constants import WORKSPACE


def build_llm_system_prompt(code_dir: str) -> str:
    """
    Constrain the agent to the active per-prompt output folder.
    """
    rel_code_dir = os.path.relpath(code_dir, WORKSPACE)
    return (
        "SYSTEM INSTRUCTION:\n"
        "You are generating code for a constrained workspace run.\n"
        f"The active writable output folder is '{rel_code_dir}' "
        f"(absolute path: '{code_dir}').\n"
        "Do not suggest or rely on modifying files outside that folder.\n"
        "Treat files outside that folder as read-only context.\n"
        "Do not hardcode the full expected output string verbatim if it contains the result.\n"
        "Compute the requested result in code and construct/emit the output from that computed value.\n"
        "Return only the requested output content (source code or JSON edit instructions).\n"
    )


def build_task_contract_prompt(
    prompt_name: str,
    toolchain: str,
    board_name: str,
    uart_addr: str,
    expected_output: str,
    formatted_prompt: str,
) -> str:
    """
    Compact task contract that is prepended on every attempt so retries do not
    lose critical constraints from the initial task prompt.
    """
    return (
        "TASK CONTRACT (applies to every attempt, including retries):\n"
        f"- Prompt template: {prompt_name}\n"
        f"- Toolchain: {toolchain}\n"
        f"- Board: {board_name}\n"
        f"- UART data register address is FIXED for this run: {uart_addr}\n"
        "- Do NOT try alternate UART addresses unless the user explicitly asks.\n"
        "- To print on the ARM FVP, write the string byte-by-byte to the UART0 data register.\n"
        "- Also use semihosting to print to the console to ensure visibility in simulation logs.\n"
        f"- Expected output requirement remains: the simulator output must contain '{expected_output}'\n"
        "- Compute the result in code; do not hardcode the result string verbatim.\n"
        "- The original task statement below remains in force for all attempts.\n\n"
        "Original task statement:\n"
        f"{formatted_prompt}\n"
    )


def build_repo_task_contract_prompt(
    *,
    prompt_name: str,
    repo_dir: str,
    entry_file_rel: str,
    build_cmd: str,
    test_cmd: str | None,
    formatted_prompt: str,
) -> str:
    test_line = f"- Test command: {test_cmd}\n" if test_cmd else ""
    return (
        "TASK CONTRACT (repo mode; applies to every attempt, including retries):\n"
        f"- Prompt template: {prompt_name}\n"
        f"- Repository root: {repo_dir}\n"
        f"- Primary file: {entry_file_rel}\n"
        f"- Build command: {build_cmd}\n"
        f"{test_line}"
        "- Make the smallest correct set of file changes.\n"
        "- Prefer JSON edit instructions in incremental mode.\n"
        "- The original task statement below remains in force for all attempts.\n\n"
        "Original task statement:\n"
        f"{formatted_prompt}\n"
    )


def build_edit_retry_prompt(current_source: str, issue_text: str) -> str:
    """
    Ask the LLM to minimally edit the current source instead of rewriting it.
    """
    return (
        f"{issue_text}\n\n"
        "Apply the smallest possible fix to the current `agent_code.s`.\n"
        "Return ONLY JSON with this shape (no prose, no markdown):\n"
        "{\n"
        '  "edits": [\n'
        "    {\n"
        '      "op": "replace_snippet",\n'
        '      "path": "relative/path/to/file",\n'
        '      "new_path": "relative/path/to/new_file",\n'
        '      "old": "...",\n'
        '      "new": "...",\n'
        '      "anchor": "...",\n'
        '      "text": "...",\n'
        '      "content": "...",\n'
        '      "occurrence": 1\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "JSON EDIT RULES (critical):\n"
        "- Allowed op values: replace_snippet, delete_snippet, insert_before, insert_after, append_text, prepend_text, replace_entire_file, create_file, delete_file, move_file.\n"
        "- `path` must be a relative path under the active writable folder. Never use absolute paths and never use `..` segments.\n"
        "- For text edit ops, omit `path` only when editing `agent_code.s`; include `path` for any other file.\n"
        "- `create_file` requires `path` + `content`. `delete_file` requires `path`. `move_file` requires `path` + `new_path`.\n"
        "- Only include fields required by the chosen op.\n"
        "- `replace_snippet` and `delete_snippet` must use exact snippets from the CURRENT file.\n"
        "- If a snippet may appear multiple times, set `occurrence` (1-based).\n"
        "- Do not include explanations, markdown fences, or any non-JSON text.\n"
        "- Prefer a small number of focused edits over replacing the entire file.\n\n"
        "Current `agent_code.s`:\n"
        "```assembly\n"
        f"{current_source}\n"
        "```\n"
    )


def build_edit_apply_issue_prompt(error: str, last_attempt_feedback: str) -> str:
    feedback = (
        "\nMost recent compile/runtime feedback from the previous attempt "
        "(use this to fix the edit content, not just formatting):\n"
        f"{last_attempt_feedback}\n\n"
        if last_attempt_feedback
        else "\n"
    )
    return (
        "Your previous response could not be applied as JSON edit instructions.\n"
        f"Edit apply error: {error}\n"
        f"{feedback}"
    )


def build_edit_apply_fallback_full_source_prompt(current_source: str, edit_apply_issue: str) -> str:
    return (
        f"{edit_apply_issue}"
        "Your intended fix may be directionally correct, but the edit instructions were not "
        "safe to apply to the current file exactly.\n\n"
        "For the next retry, do NOT return JSON edits.\n"
        "Return ONLY a full replacement for `agent_code.s` (no prose, no markdown).\n"
        "Make the smallest logical fix needed while preserving the working parts.\n\n"
        "Current `agent_code.s`:\n"
        "```assembly\n"
        f"{current_source}\n"
        "```\n"
    )


def build_source_validation_issue_prompt(source_validation_error: str) -> str:
    return (
        "Your previous response contained non-assembly text and was rejected before writing `agent_code.s`.\n"
        f"Validation error: {source_validation_error}\n\n"
        "Return ONLY valid ARM assembly source for `agent_code.s` (no prose, no markdown, no logs).\n"
    )


def build_compile_failure_edit_issue(compile_error: str) -> str:
    return (
        "Your previous code failed to compile with the following error:\n"
        f"{compile_error}\n\n"
        "Please fix the code."
    )


def build_compile_failure_full_source_prompt(compile_error: str) -> str:
    return (
        "Your previous code failed to compile with the following error:\n"
        f"{compile_error}\n\n"
        "Please fix the code and return ONLY the corrected assembly/C code."
    )


def build_verification_failure_issue(stage: str | None, output: str, timed_out: bool) -> str:
    stage_text = stage or "verification"
    timeout_text = "timed out" if timed_out else "failed"
    return (
        f"The {stage_text} command {timeout_text}.\n"
        f"Command output:\n{output}\n\n"
        "Please fix the implementation so verification passes."
    )


def build_verification_failure_full_source_prompt(stage: str | None, output: str, timed_out: bool) -> str:
    return (
        build_verification_failure_issue(stage, output, timed_out)
        + "\nReturn ONLY the corrected source output (no prose, no markdown)."
    )


def build_timeout_edit_issue(board_name: str, run_output: str) -> str:
    return (
        f"The code compiled successfully, but running it in {board_name} timed out after multiple attempts.\n"
        f"Output before timeout:\n{run_output}\n\n"
        "Ensure you are not stuck in an infinite loop before printing the required output. Please fix the logic."
    )


def build_timeout_full_source_prompt(board_name: str, run_output: str) -> str:
    return (
        f"The code compiled successfully, but running it in {board_name} timed out after multiple attempts.\n"
        f"Output before timeout:\n{run_output}\n\n"
        "Ensure you are not stuck in an infinite loop before printing the required output. "
        "Please fix the logic and try again. Return ONLY the corrected assembly/C code."
    )


def build_output_mismatch_edit_issue(expected_output: str, run_output: str) -> str:
    return (
        "The code compiled successfully and completed, but the expected output was not found.\n"
        f"Output:\n{run_output}\n\n"
        f"We expect the exact string '{expected_output}' to be printed to the UART. Please fix the logic."
    )


def build_output_mismatch_full_source_prompt(expected_output: str, run_output: str) -> str:
    return (
        "The code compiled successfully and completed, but the expected output was not found.\n"
        f"Output:\n{run_output}\n\n"
        f"We expect the exact string '{expected_output}' to be printed to the UART. "
        "Please fix the logic and return ONLY the corrected assembly/C code."
    )


# Backward-compatible aliases while migrating from unified diff patching.
def build_patch_retry_prompt(current_source: str, issue_text: str) -> str:
    return build_edit_retry_prompt(current_source, issue_text)


def build_patch_apply_issue_prompt(error: str, last_attempt_feedback: str) -> str:
    return build_edit_apply_issue_prompt(error, last_attempt_feedback)


def build_patch_context_mismatch_full_source_prompt(current_source: str, patch_apply_issue: str) -> str:
    return build_edit_apply_fallback_full_source_prompt(current_source, patch_apply_issue)


def build_compile_failure_patch_issue(compile_error: str) -> str:
    return build_compile_failure_edit_issue(compile_error)


def build_timeout_patch_issue(board_name: str, run_output: str) -> str:
    return build_timeout_edit_issue(board_name, run_output)


def build_output_mismatch_patch_issue(expected_output: str, run_output: str) -> str:
    return build_output_mismatch_edit_issue(expected_output, run_output)
