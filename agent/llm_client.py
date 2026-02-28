import os
import subprocess
import sys

from agent.prompting import build_llm_system_prompt

FALLBACK_SOURCE = "    .global _start\n_start:\n    mov r0, #42\n"


def strip_markdown_fences(text: str) -> str:
    lines = text.split("\n")
    has_fence = any(line.startswith("```") for line in lines)
    if not has_fence:
        return text

    code_lines = []
    in_code_block = False
    for line in lines:
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            code_lines.append(line)
    return "\n".join(code_lines)


def call_llm(
    input_prompt: str,
    writable_dir: str,
    log_dir: str,
    task_contract_prompt: str = "",
) -> str:
    """
    Call the local `gemini` CLI and return generated source text.
    """
    prompt_parts = [build_llm_system_prompt(writable_dir)]
    if task_contract_prompt:
        prompt_parts.append(task_contract_prompt)
    prompt_parts.append(input_prompt)
    prompt = "\n".join(prompt_parts)
    print(f"\n[LLM] Generating code... (Prompt length: {len(prompt)})")
    print(f"[LLM] --- Prompt Sent ---\n{prompt}\n-----------------------")

    os.makedirs(log_dir, exist_ok=True)
    prompt_file = os.path.join(log_dir, "current_prompt.txt")
    with open(prompt_file, "w") as f:
        f.write(prompt)

    debug_log_path = os.path.join(log_dir, "llm_debug.log")
    print(f"[LLM] --- Streaming Response (Debug logs routed to {debug_log_path}) ---")
    try:
        with open(debug_log_path, "a") as debug_file:
            debug_file.write(f"\n\n--- New Prompt Execution (Length: {len(prompt)}) ---\n")
            use_stdin_prompt = len(prompt) > 8000
            gemini_cmd = ["gemini", "-d"] if use_stdin_prompt else ["gemini", "-d", prompt]
            process = subprocess.Popen(
                gemini_cmd,
                stdin=subprocess.PIPE if use_stdin_prompt else None,
                stdout=subprocess.PIPE,
                stderr=debug_file,
                text=True,
                bufsize=1,
            )

            if use_stdin_prompt and process.stdin is not None:
                process.stdin.write(prompt)
                process.stdin.close()

            response_lines = []
            if process.stdout is not None:
                for line in iter(process.stdout.readline, ""):
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    response_lines.append(line)
                process.stdout.close()
            process.wait()

        if process.returncode != 0:
            print(f"[LLM] Error calling Gemini CLI. Check {debug_log_path} for details.")
            return FALLBACK_SOURCE

        response = "".join(response_lines)
        final_code = strip_markdown_fences(response)
        print(f"[LLM] --- Code Received ---\n{final_code}\n---------------------------")
        return final_code
    except OSError as e:
        print(f"[LLM] Error calling Gemini CLI: {e}")
        return FALLBACK_SOURCE
