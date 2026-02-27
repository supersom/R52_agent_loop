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
