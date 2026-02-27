import difflib
import os

from agent.history import RunHistory
from agent.llm_client import call_llm
from agent.models import LoopConfig
from agent.patching import apply_unified_diff_patch
from agent.prompting import (
    build_compile_failure_full_source_prompt,
    build_compile_failure_patch_issue,
    build_output_mismatch_full_source_prompt,
    build_output_mismatch_patch_issue,
    build_patch_apply_issue_prompt,
    build_patch_context_mismatch_full_source_prompt,
    build_patch_retry_prompt,
    build_source_validation_issue_prompt,
    build_timeout_full_source_prompt,
    build_timeout_patch_issue,
)
from agent.response_filters import (
    extract_arm_asm_block,
    sanitize_full_source_text,
    sanitize_unified_diff_patch_text,
    validate_arm_asm_source_text,
)
from agent.toolchain import compile_code, run_in_simulator
from agent.workspace import snapshot_successful_run


def run_agent_loop(config: LoopConfig) -> None:
    current_prompt = config.initial_prompt
    response_mode = "full_source"
    last_attempt_feedback = ""
    run_history = RunHistory(config.history_file)

    current_source = ""
    if os.path.exists(config.source_file):
        with open(config.source_file, "r") as f:
            current_source = f.read()
        print(f"[Info] Loaded existing working source from {config.source_file} for iterative updates")

    for attempt in range(1, config.max_retries + 1):
        print(f"\n--- Attempt {attempt}/{config.max_retries} ---")

        llm_response = call_llm(current_prompt, config.code_dir, config.task_contract_prompt)
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
                patch_apply_issue = build_patch_apply_issue_prompt(str(e), last_attempt_feedback)
                if "Patch context does not match current source" in str(e):
                    print("[Loop] Switching next retry to full source mode due to patch context mismatch.")
                    current_prompt = build_patch_context_mismatch_full_source_prompt(
                        current_source,
                        patch_apply_issue,
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

            validation_issue = build_source_validation_issue_prompt(source_validation_error)
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

        with open(config.source_file, "w") as f:
            f.write(generated_code)

        compile_success, compile_error = compile_code(
            source_file=config.source_file,
            elf_file=config.elf_file,
            toolchain=config.toolchain,
            code_dir=config.code_dir,
            workspace=config.workspace,
            binaries=config.toolchain_binaries,
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
            if config.incremental:
                current_prompt = build_patch_retry_prompt(
                    current_source,
                    build_compile_failure_patch_issue(compile_error),
                )
                response_mode = "patch"
            else:
                current_prompt = build_compile_failure_full_source_prompt(compile_error)
                response_mode = "full_source"
            continue

        run_success = False
        run_output = ""
        timed_out = False
        current_timeout = config.timeout_sec

        for _ in range(3):
            success, output, t_out = run_in_simulator(
                elf_file=config.elf_file,
                toolchain=config.toolchain,
                binaries=config.toolchain_binaries,
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
                f"Simulator output before timeout in {config.board_name}:\n"
                f"{run_output}"
            )
            if config.incremental:
                current_prompt = build_patch_retry_prompt(
                    current_source,
                    build_timeout_patch_issue(config.board_name, run_output),
                )
                response_mode = "patch"
            else:
                current_prompt = build_timeout_full_source_prompt(config.board_name, run_output)
                response_mode = "full_source"
            continue

        if not run_success or config.expected_output not in run_output:
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
            if config.incremental:
                current_prompt = build_patch_retry_prompt(
                    current_source,
                    build_output_mismatch_patch_issue(config.expected_output, run_output),
                )
                response_mode = "patch"
            else:
                current_prompt = build_output_mismatch_full_source_prompt(config.expected_output, run_output)
                response_mode = "full_source"
            continue

        entry["run_success"] = run_success
        entry["run_output"] = RunHistory.lines(run_output)
        entry["timed_out"] = False
        entry["attempt_result"] = "success"
        run_history.flush()
        snapshot_dir = snapshot_successful_run(config.code_dir)
        print("\n=== SUCCESS! The agent wrote working ARM code! ===")
        print("Final Output:\n", run_output)
        print(f"[Info] Snapshot saved to {snapshot_dir}")
        break
    else:
        print(f"\n=== FAILED: Agent could not fix the code after {config.max_retries} attempts ===")

    print(f"\n[Info] Final run history saved to {config.history_file}")
