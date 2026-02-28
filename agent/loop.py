import difflib
import os

from agent.edits import apply_workspace_edit_instructions, parse_edit_instructions
from agent.history import RunHistory
from agent.llm_client import call_llm
from agent.models import LoopConfig
from agent.retry_policy import decide_next_retry
from agent.response_filters import (
    extract_arm_asm_block,
    sanitize_full_source_text,
    validate_arm_asm_source_text,
)
from agent.toolchain import compile_code, run_in_simulator, run_repo_verification
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
    if config.incremental and (current_source or config.repo_mode):
        response_mode = "edits"
        print("[Info] Incremental mode enabled; starting retries in JSON edits mode.")

    for attempt in range(1, config.max_retries + 1):
        print(f"\n--- Attempt {attempt}/{config.max_retries} ---")

        llm_response = call_llm(current_prompt, config.code_dir, config.task_contract_prompt)
        previous_code = current_source
        parsed_edits = None
        edit_output_sanitized = False
        edited_files = None
        if response_mode == "edits":
            try:
                parsed_edits, edit_output_sanitized = parse_edit_instructions(llm_response)
                if edit_output_sanitized:
                    print("[Loop] Stripped non-JSON wrapper text from edits response before applying.")
                edited_files = apply_workspace_edit_instructions(
                    config.code_dir,
                    parsed_edits,
                    default_path=config.entry_file_rel,
                )
                if not os.path.exists(config.source_file):
                    raise ValueError(
                        f"Incremental edits removed required source file '{config.entry_file_rel}'"
                    )
                with open(config.source_file, "r") as f:
                    generated_code = f.read()
            except ValueError as e:
                print(f"[Loop] Could not apply edit response: {e}")
                run_history.append(
                    {
                        "attempt": attempt,
                        "prompt": current_prompt,
                        "response_mode": response_mode,
                        "generated_code": llm_response.splitlines(),
                        "diff": [],
                        "edited_files": edited_files,
                        "edit_operations": parsed_edits,
                        "edit_apply_success": False,
                        "edit_apply_error": str(e),
                        "edit_output_sanitized": edit_output_sanitized,
                        "compile_success": None,
                        "compile_error": None,
                        "run_success": None,
                        "run_output": None,
                        "timed_out": None,
                        "attempt_result": "edit_apply_failed",
                    }
                )
                run_history.flush()
                retry_decision = decide_next_retry(
                    outcome="edit_apply_failed",
                    current_mode=response_mode,
                    incremental=config.incremental,
                    incremental_strict=config.incremental_strict,
                    current_source=current_source,
                    expected_output=config.expected_output,
                    board_name=config.board_name,
                    edit_apply_error=str(e),
                    last_attempt_feedback=last_attempt_feedback,
                )
                if retry_decision.note:
                    print(f"[Loop] {retry_decision.note}")
                current_prompt = retry_decision.next_prompt
                response_mode = retry_decision.next_mode
                continue
        else:
            sanitized_full_source = sanitize_full_source_text(llm_response)
            if sanitized_full_source != llm_response:
                print("[Loop] Stripped trailing non-code output from full-source response before writing.")
            if config.repo_mode:
                generated_code = sanitized_full_source
            else:
                extracted_source, extraction_note = extract_arm_asm_block(sanitized_full_source)
                if extraction_note:
                    print(f"[Loop] {extraction_note} from full-source response before validation.")
                generated_code = extracted_source

        source_validation_error = None if config.repo_mode else validate_arm_asm_source_text(generated_code)
        if source_validation_error:
            print(f"[Loop] Rejected non-assembly response before writing source: {source_validation_error}")
            run_history.append(
                {
                    "attempt": attempt,
                    "prompt": current_prompt,
                    "response_mode": response_mode,
                    "generated_code": generated_code.splitlines(),
                    "diff": [],
                    "edited_files": edited_files if response_mode == "edits" else None,
                    "edit_operations": parsed_edits if response_mode == "edits" else None,
                    "edit_apply_success": True if response_mode == "edits" else None,
                    "edit_apply_error": None,
                    "edit_output_sanitized": edit_output_sanitized if response_mode == "edits" else None,
                    "compile_success": None,
                    "compile_error": [f"Source validation failed: {source_validation_error}"],
                    "run_success": None,
                    "run_output": None,
                    "timed_out": None,
                    "attempt_result": "source_validation_failed",
                }
            )
            run_history.flush()
            retry_decision = decide_next_retry(
                outcome="source_validation_failed",
                current_mode=response_mode,
                incremental=config.incremental,
                incremental_strict=config.incremental_strict,
                current_source=current_source,
                expected_output=config.expected_output,
                board_name=config.board_name,
                validation_error=source_validation_error,
            )
            current_prompt = retry_decision.next_prompt
            response_mode = retry_decision.next_mode
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
                "edited_files": edited_files if response_mode == "edits" else None,
                "edit_operations": parsed_edits if response_mode == "edits" else None,
                "edit_apply_success": True if response_mode == "edits" else None,
                "edit_apply_error": None,
                "edit_output_sanitized": edit_output_sanitized if response_mode == "edits" else None,
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

        source_parent = os.path.dirname(config.source_file)
        if source_parent:
            os.makedirs(source_parent, exist_ok=True)
        with open(config.source_file, "w") as f:
            f.write(generated_code)

        if config.repo_mode:
            verify_result = run_repo_verification(
                repo_dir=config.repo_dir or config.code_dir,
                build_cmd=config.build_cmd or "",
                test_cmd=config.test_cmd,
                timeout_sec=config.verify_timeout_sec,
            )
            entry["verify_success"] = verify_result.success
            entry["verify_stage"] = verify_result.stage
            entry["verify_timed_out"] = verify_result.timed_out
            entry["verify_output"] = RunHistory.lines(verify_result.output)

            if not verify_result.success:
                entry["attempt_result"] = "verification_failed"
                run_history.flush()
                print("[Loop] Repo verification failed. Feeding output back to agent...")
                last_attempt_feedback = verify_result.output
                retry_decision = decide_next_retry(
                    outcome="verification_failed",
                    current_mode=response_mode,
                    incremental=config.incremental,
                    incremental_strict=config.incremental_strict,
                    current_source=current_source,
                    expected_output=config.expected_output,
                    board_name=config.board_name,
                    verification_error=verify_result.output,
                    verification_stage=verify_result.stage,
                    verification_timed_out=verify_result.timed_out,
                )
                current_prompt = retry_decision.next_prompt
                response_mode = retry_decision.next_mode
                continue

            entry["run_success"] = True
            entry["run_output"] = RunHistory.lines(verify_result.output)
            entry["timed_out"] = False
            entry["attempt_result"] = "success"
            run_history.flush()
            snapshot_dir = snapshot_successful_run(config.code_dir)
            print("\n=== SUCCESS! Repository verification passed. ===")
            print(f"[Info] Snapshot saved to {snapshot_dir}")
            break

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
            retry_decision = decide_next_retry(
                outcome="compile_failed",
                current_mode=response_mode,
                incremental=config.incremental,
                incremental_strict=config.incremental_strict,
                current_source=current_source,
                expected_output=config.expected_output,
                board_name=config.board_name,
                compile_error=compile_error,
            )
            current_prompt = retry_decision.next_prompt
            response_mode = retry_decision.next_mode
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
            retry_decision = decide_next_retry(
                outcome="run_timed_out",
                current_mode=response_mode,
                incremental=config.incremental,
                incremental_strict=config.incremental_strict,
                current_source=current_source,
                expected_output=config.expected_output,
                board_name=config.board_name,
                run_output=run_output,
            )
            current_prompt = retry_decision.next_prompt
            response_mode = retry_decision.next_mode
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
            retry_decision = decide_next_retry(
                outcome=entry["attempt_result"],
                current_mode=response_mode,
                incremental=config.incremental,
                incremental_strict=config.incremental_strict,
                current_source=current_source,
                expected_output=config.expected_output,
                board_name=config.board_name,
                run_output=run_output,
            )
            current_prompt = retry_decision.next_prompt
            response_mode = retry_decision.next_mode
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
