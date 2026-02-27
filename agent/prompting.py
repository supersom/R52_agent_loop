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
        "Return only the requested output content (source code or unified diff patch).\n"
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


def build_patch_retry_prompt(current_source: str, issue_text: str) -> str:
    """
    Ask the LLM to minimally patch the current source instead of rewriting it.
    """
    return (
        f"{issue_text}\n\n"
        "Apply the smallest possible fix to the current `agent_code.s`.\n"
        "Return ONLY a unified diff patch for `agent_code.s` (no prose, no markdown).\n"
        "PATCH ACCURACY RULES (critical):\n"
        "- The unified diff must apply cleanly to the CURRENT `agent_code.s` shown below.\n"
        "- Copy unchanged context lines VERBATIM from the current file, including blank lines, spaces, and comments.\n"
        "- Do not guess hunk headers. Ensure each `@@ -old,+new @@` header matches the exact context positions in the current file.\n"
        "- The first context line after each hunk header must exactly match the current file at that old-line position.\n"
        "- Do not include prose, explanations, markdown fences, or any text before/after the patch.\n"
        "Expected format:\n"
        "--- agent_code.s\n"
        "+++ agent_code.s\n"
        "@@ ... @@\n"
        "...\n\n"
        "Current `agent_code.s`:\n"
        "```assembly\n"
        f"{current_source}\n"
        "```\n"
    )


def build_patch_apply_issue_prompt(error: str, last_attempt_feedback: str) -> str:
    feedback = (
        "\nMost recent compile/runtime feedback from the previous attempt "
        "(use this to fix the patch, not just the formatting):\n"
        f"{last_attempt_feedback}\n\n"
        if last_attempt_feedback
        else "\n"
    )
    return (
        "Your previous response could not be applied as a unified diff patch.\n"
        f"Patch apply error: {error}\n"
        f"{feedback}"
    )


def build_patch_context_mismatch_full_source_prompt(current_source: str, patch_apply_issue: str) -> str:
    return (
        f"{patch_apply_issue}"
        "Your patch content may be directionally correct, but the unified diff context did not "
        "match the current file exactly.\n\n"
        "For the next retry, do NOT return a patch.\n"
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


def build_compile_failure_patch_issue(compile_error: str) -> str:
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


def build_timeout_patch_issue(board_name: str, run_output: str) -> str:
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


def build_output_mismatch_patch_issue(expected_output: str, run_output: str) -> str:
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
