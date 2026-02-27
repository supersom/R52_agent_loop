import difflib
import os

from agent.history import RunHistory
from agent.llm_client import call_llm
from agent.patching import apply_unified_diff_patch
from agent.prompting import build_patch_retry_prompt
from agent.response_filters import (
    extract_arm_asm_block,
    sanitize_full_source_text,
    sanitize_unified_diff_patch_text,
    validate_arm_asm_source_text,
)
from agent.toolchain import ToolchainBinaries, compile_code, run_in_simulator
from agent.workspace import snapshot_successful_run


def run_agent_loop(
    *,
    toolchain: str,
    incremental: bool,
    expected_output: str,
    board_name: str,
    code_dir: str,
    source_file: str,
    elf_file: str,
    history_file: str,
    initial_prompt: str,
    task_contract_prompt: str,
    workspace: str,
    toolchain_binaries: ToolchainBinaries,
    max_retries: int,
    timeout_sec: int = 2,
) -> None:
    current_prompt = initial_prompt
    response_mode = "full_source"
    last_attempt_feedback = ""
    run_history = RunHistory(history_file)

    current_source = ""
    if os.path.exists(source_file):
        with open(source_file, "r") as f:
            current_source = f.read()
        print(f"[Info] Loaded existing working source from {source_file} for iterative updates")

    for attempt in range(1, max_retries + 1):
        print(f"\n--- Attempt {attempt}/{max_retries} ---")

        llm_response = call_llm(current_prompt, code_dir, task_contract_prompt)
        previous_code = current_source
        if response_mode == "patch":
            sanitized_patch = llm_response
            patch_output_sanitized = False
            try:
                sanitized_patch = sanitize_unified_diff_patch_text(llm_response, current_source)
                patch_output_sanitized = sanitized_patch != llm_response
                if patch_output_sanitized:
                    print("[Loop] Stripped trailing non-diff output from patch response before applying.")
                generated_code = apply_unified_diff_patch(current_source, sanitized_patch)
            except ValueError as e:
                print(f"[Loop] Could not apply patch response: {e}")
                run_history.append(
                    {
                        "attempt": attempt,
                        "prompt": current_prompt,
                        "response_mode": response_mode,
                        "generated_code": llm_response.splitlines(),
                        "diff": [],
                        "patch_apply_success": False,
                        "patch_apply_error": str(e),
                        "patch_output_sanitized": patch_output_sanitized,
                        "compile_success": None,
                        "compile_error": None,
                        "run_success": None,
                        "run_output": None,
                        "timed_out": None,
                        "attempt_result": "patch_apply_failed",
                    }
                )
                run_history.flush()
                patch_apply_issue = (
                    "Your previous response could not be applied as a unified diff patch.\n"
                    + f"Patch apply error: {e}\n"
                    + (
                        "\nMost recent compile/runtime feedback from the previous attempt "
                        "(use this to fix the patch, not just the formatting):\n"
                        f"{last_attempt_feedback}\n\n"
                        if last_attempt_feedback
                        else "\n"
                    )
                )
                if "Patch context does not match current source" in str(e):
                    print("[Loop] Switching next retry to full source mode due to patch context mismatch.")
                    current_prompt = (
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
                    response_mode = "full_source"
                else:
                    current_prompt = build_patch_retry_prompt(
                        current_source,
                        patch_apply_issue + "Return a valid unified diff patch against the current `agent_code.s`.",
                    )
                    response_mode = "patch"
                continue
        else:
            sanitized_full_source = sanitize_full_source_text(llm_response)
            if sanitized_full_source != llm_response:
                print("[Loop] Stripped trailing non-code output from full-source response before writing.")
            extracted_source, extraction_note = extract_arm_asm_block(sanitized_full_source)
            if extraction_note:
                print(f"[Loop] {extraction_note} from full-source response before validation.")
            generated_code = extracted_source

        source_validation_error = validate_arm_asm_source_text(generated_code)
        if source_validation_error:
            print(f"[Loop] Rejected non-assembly response before writing source: {source_validation_error}")
            run_history.append(
                {
                    "attempt": attempt,
                    "prompt": current_prompt,
                    "response_mode": response_mode,
                    "generated_code": generated_code.splitlines(),
                    "diff": [],
                    "patch_apply_success": True if response_mode == "patch" else None,
                    "patch_apply_error": None,
                    "patch_output_sanitized": patch_output_sanitized if response_mode == "patch" else None,
                    "compile_success": None,
                    "compile_error": [f"Source validation failed: {source_validation_error}"],
                    "run_success": None,
                    "run_output": None,
                    "timed_out": None,
                    "attempt_result": "source_validation_failed",
                }
            )
            run_history.flush()

            validation_issue = (
                "Your previous response contained non-assembly text and was rejected before writing `agent_code.s`.\n"
                f"Validation error: {source_validation_error}\n\n"
                "Return ONLY valid ARM assembly source for `agent_code.s` (no prose, no markdown, no logs).\n"
            )
            if response_mode == "patch":
                current_prompt = build_patch_retry_prompt(current_source, validation_issue)
                response_mode = "patch"
            else:
                current_prompt = validation_issue
                response_mode = "full_source"
            continue

        diff = list(
            difflib.unified_diff(
                previous_code.splitlines(keepends=True),
                generated_code.splitlines(keepends=True),
                fromfile=f"Attempt_{attempt-1}",
                tofile=f"Attempt_{attempt}",
            )
        )
        diff_str = "".join(diff)

        run_history.append(
            {
                "attempt": attempt,
                "prompt": current_prompt,
                "response_mode": response_mode,
                "generated_code": generated_code.splitlines(),
                "diff": diff_str.splitlines(),
                "patch_apply_success": True if response_mode == "patch" else None,
                "patch_apply_error": None,
                "patch_output_sanitized": patch_output_sanitized if response_mode == "patch" else None,
                "compile_success": None,
                "compile_error": None,
                "run_success": None,
                "run_output": None,
                "timed_out": None,
                "attempt_result": "generated",
            }
        )

        run_history.flush()
        entry = run_history.last()

        current_source = generated_code

        with open(source_file, "w") as f:
            f.write(generated_code)

        compile_success, compile_error = compile_code(
            source_file=source_file,
            elf_file=elf_file,
            toolchain=toolchain,
            code_dir=code_dir,
            workspace=workspace,
            binaries=toolchain_binaries,
        )
        entry["compile_success"] = compile_success
        entry["compile_error"] = RunHistory.lines(compile_error if compile_error else None)

        if not compile_success:
            entry["attempt_result"] = "compile_failed"
            run_history.flush()
            print("[Loop] Compilation failed. Feeding error back to agent...")
            last_attempt_feedback = (
                "Compilation failed with this error output:\n"
                f"{compile_error}"
            )
            if incremental:
                current_prompt = build_patch_retry_prompt(
                    current_source,
                    (
                        "Your previous code failed to compile with the following error:\n"
                        f"{compile_error}\n\n"
                        "Please fix the code."
                    ),
                )
                response_mode = "patch"
            else:
                current_prompt = (
                    "Your previous code failed to compile with the following error:\n"
                    f"{compile_error}\n\n"
                    "Please fix the code and return ONLY the corrected assembly/C code."
                )
                response_mode = "full_source"
            continue

        run_success = False
        run_output = ""
        timed_out = False
        current_timeout = timeout_sec

        for _ in range(3):
            success, output, t_out = run_in_simulator(
                elf_file=elf_file,
                toolchain=toolchain,
                binaries=toolchain_binaries,
                timeout_sec=current_timeout,
            )
            run_output = output
            if not t_out:
                run_success = success
                timed_out = False
                break
            print(f"[Simulator] Timed out after {current_timeout}s. Retrying with longer timeout...")
            current_timeout *= 2
            timed_out = True

        if timed_out:
            entry["run_success"] = False
            entry["run_output"] = RunHistory.lines(run_output)
            entry["timed_out"] = True
            entry["attempt_result"] = "run_timed_out"
            run_history.flush()
            print("[Loop] Code consistently timed out. Feeding back to agent...")
            last_attempt_feedback = (
                f"Simulator output before timeout in {board_name}:\n"
                f"{run_output}"
            )
            if incremental:
                current_prompt = build_patch_retry_prompt(
                    current_source,
                    (
                        f"The code compiled successfully, but running it in {board_name} timed out after multiple attempts.\n"
                        f"Output before timeout:\n{run_output}\n\n"
                        "Ensure you are not stuck in an infinite loop before printing the required output. Please fix the logic."
                    ),
                )
                response_mode = "patch"
            else:
                current_prompt = (
                    f"The code compiled successfully, but running it in {board_name} timed out after multiple attempts.\n"
                    f"Output before timeout:\n{run_output}\n\n"
                    "Ensure you are not stuck in an infinite loop before printing the required output. "
                    "Please fix the logic and try again. Return ONLY the corrected assembly/C code."
                )
                response_mode = "full_source"
            continue

        if not run_success or expected_output not in run_output:
            entry["run_success"] = run_success
            entry["run_output"] = RunHistory.lines(run_output)
            entry["timed_out"] = False
            entry["attempt_result"] = "run_output_mismatch" if run_success else "run_failed"
            run_history.flush()
            print(f"[Loop] Runtime failed or output was incorrect. Output:\n{run_output}")
            last_attempt_feedback = (
                "Runtime completed but expected output was not found. Full simulator output:\n"
                f"{run_output}"
            )
            if incremental:
                current_prompt = build_patch_retry_prompt(
                    current_source,
                    (
                        "The code compiled successfully and completed, but the expected output was not found.\n"
                        f"Output:\n{run_output}\n\n"
                        f"We expect the exact string '{expected_output}' to be printed to the UART. Please fix the logic."
                    ),
                )
                response_mode = "patch"
            else:
                current_prompt = (
                    "The code compiled successfully and completed, but the expected output was not found.\n"
                    f"Output:\n{run_output}\n\n"
                    f"We expect the exact string '{expected_output}' to be printed to the UART. "
                    "Please fix the logic and return ONLY the corrected assembly/C code."
                )
                response_mode = "full_source"
            continue

        entry["run_success"] = run_success
        entry["run_output"] = RunHistory.lines(run_output)
        entry["timed_out"] = False
        entry["attempt_result"] = "success"
        run_history.flush()
        snapshot_dir = snapshot_successful_run(code_dir)
        print("\n=== SUCCESS! The agent wrote working ARM code! ===")
        print("Final Output:\n", run_output)
        print(f"[Info] Snapshot saved to {snapshot_dir}")
        break
    else:
        print(f"\n=== FAILED: Agent could not fix the code after {max_retries} attempts ===")

    print(f"\n[Info] Final run history saved to {history_file}")
