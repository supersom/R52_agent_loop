import subprocess
import os
import sys
import argparse
import difflib
from agent.history import RunHistory
from agent.llm_client import call_llm
from agent.patching import apply_unified_diff_patch
from agent.prompting import (
    build_patch_retry_prompt,
    build_task_contract_prompt,
)
from agent.response_filters import (
    extract_arm_asm_block,
    sanitize_full_source_text,
    sanitize_unified_diff_patch_text,
    validate_arm_asm_source_text,
)
from agent.toolchain import (
    compile_code,
    get_target_details,
    load_toolchain_binaries_from_env,
    run_in_simulator,
)
from agent.workspace import (
    collect_existing_code_context,
    get_prompt_run_dir,
    load_dotenv,
    snapshot_successful_run,
)

# You can use the `google-genai` package or direct API calls for the LLM part later.
# For now, we stub out the LLM call.

MAX_RETRIES = 10
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.join(WORKSPACE, "code")
GENERATED_SOURCE_NAME = "agent_code.s"
GENERATED_ELF_NAME = "agent_code.elf"

load_dotenv(os.path.join(WORKSPACE, ".env"))
TOOLCHAIN_BINARIES = load_toolchain_binaries_from_env()

def check_git_status(auto_yes: bool = False):
    """
    Check if there are uncommitted changes. If so, ask the user if they want to proceed.
    """
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        if result.stdout.strip():
            print("\n[Warning] You have uncommitted changes in your repository:")
            print(result.stdout)
            if auto_yes:
                print("[Info] Proceeding because --yes/-y was provided.")
                return
            choice = input("Do you really want to proceed? (y/N): ").strip().lower()
            if choice != 'y':
                print("Aborting.")
                sys.exit(0)
    except subprocess.CalledProcessError:
        pass # Not a git repo or git not installed

def main():
    parser = argparse.ArgumentParser(description="Agentic ARM Development Loop")
    parser.add_argument("-y", "--yes", action="store_true", help="Automatically proceed past the uncommitted-changes check")
    parser.add_argument("--toolchain", choices=["gcc", "ds5"], default="gcc", help="Toolchain to use (gcc or ds5)")
    parser.add_argument("--source", type=str, help="Path to an existing folder of code to start with.", default=None)
    parser.add_argument("--prompt", type=str, help="Path to a custom prompt file in the prompts/ folder.", default="prompts/prime_sum.txt")
    parser.add_argument("--expected", type=str, help="Expected output string from the simulator.", default="SUM: 129")
    parser.add_argument("--incremental", action="store_true", help="Use incremental patch retries (unified diff) instead of full-source retries")
    args = parser.parse_args()

    check_git_status(auto_yes=args.yes)

    print(f"=== Starting Agentic ARM Development Loop (Toolchain: {args.toolchain}, Incremental: {args.incremental}) ===")
    
    uart_addr, board_name = get_target_details(args.toolchain)
    existing_code_context = collect_existing_code_context(args.source)

    # Read the prompt file
    prompt_path = os.path.join(WORKSPACE, args.prompt)
    if not os.path.exists(prompt_path):
        print(f"Error: Prompt file not found at {prompt_path}")
        sys.exit(1)
        
    with open(prompt_path, 'r') as f:
        base_prompt_text = f.read()

    code_dir = get_prompt_run_dir(CODE_ROOT, prompt_path)
    os.makedirs(code_dir, exist_ok=True)
    source_file = os.path.join(code_dir, GENERATED_SOURCE_NAME)
    elf_file = os.path.join(code_dir, GENERATED_ELF_NAME)
    history_file = os.path.join(code_dir, "run_history.json")

    print(f"[Info] Prompt outputs will be written to {code_dir}")

    # Format the dynamic parts of the prompt
    formatted_prompt = base_prompt_text.format(
        uart_addr=uart_addr,
        board_name=board_name,
        expected_output=args.expected
    )
    task_contract_prompt = build_task_contract_prompt(
        prompt_name=os.path.basename(prompt_path),
        toolchain=args.toolchain,
        board_name=board_name,
        uart_addr=uart_addr,
        expected_output=args.expected,
        formatted_prompt=formatted_prompt,
    )

    initial_prompt = (
        f"CRITICAL: If an incremental feature is requested and there is existing code that met requirements prior to this incremental feature request, try to change that existing code as little as possible while implementing this feature. If you would like to improve on something that existed, jot that down in a comments and allow the developer to decide. "
        f"CRITICAL: If you start off with non-empty code, first check if that meets requirements before attempting to modify. You might not have to run this through an iteration of write-build-run - the requirements might be so different from the existing code that it is obvious that it has to be rewritten."
        f"{existing_code_context}"
    )
    
    current_prompt = initial_prompt
    response_mode = "full_source"
    timeout_sec = 2
    last_attempt_feedback = ""
    run_history = RunHistory(history_file)

    current_source = ""
    if os.path.exists(source_file):
        with open(source_file, "r") as f:
            current_source = f.read()
        print(f"[Info] Loaded existing working source from {source_file} for iterative updates")
    
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n--- Attempt {attempt}/{MAX_RETRIES} ---")
        
        # 1. Ask the Agent to write/fix the code
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
                run_history.append({
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
                })
                run_history.flush()
                patch_apply_issue = (
                    "Your previous response could not be applied as a unified diff patch.\n"
                    + f"Patch apply error: {e}\n"
                    + (
                        "\nMost recent compile/runtime feedback from the previous attempt "
                        "(use this to fix the patch, not just the formatting):\n"
                        f"{last_attempt_feedback}\n\n"
                        if last_attempt_feedback else "\n"
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
                        patch_apply_issue + "Return a valid unified diff patch against the current `agent_code.s`."
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
            run_history.append({
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
            })
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
        
        # Compute diff
        diff = list(difflib.unified_diff(
            previous_code.splitlines(keepends=True),
            generated_code.splitlines(keepends=True),
            fromfile=f"Attempt_{attempt-1}",
            tofile=f"Attempt_{attempt}"
        ))
        diff_str = "".join(diff)
        
        # Save to history
        run_history.append({
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
        })
        
        # Dump run history to JSON immediately after LLM response
        run_history.flush()
        entry = run_history.last()
        
        current_source = generated_code
        
        # 2. Save it to disk
        with open(source_file, "w") as f:
            f.write(generated_code)
            
        # 3. Try to compile it
        compile_success, compile_error = compile_code(
            source_file=source_file,
            elf_file=elf_file,
            toolchain=args.toolchain,
            code_dir=code_dir,
            workspace=WORKSPACE,
            binaries=TOOLCHAIN_BINARIES,
        )
        entry["compile_success"] = compile_success
        entry["compile_error"] = RunHistory.lines(compile_error if compile_error else None)
        
        if not compile_success:
            entry["attempt_result"] = "compile_failed"
            run_history.flush()
            print(f"[Loop] Compilation failed. Feeding error back to agent...")
            last_attempt_feedback = (
                "Compilation failed with this error output:\n"
                f"{compile_error}"
            )
            if args.incremental:
                current_prompt = build_patch_retry_prompt(
                    current_source,
                    (
                        "Your previous code failed to compile with the following error:\n"
                        f"{compile_error}\n\n"
                        "Please fix the code."
                    )
                )
                response_mode = "patch"
            else:
                current_prompt = (
                    "Your previous code failed to compile with the following error:\n"
                    f"{compile_error}\n\n"
                    "Please fix the code and return ONLY the corrected assembly/C code."
                )
                response_mode = "full_source"
            continue # Try again!
            
        # 4. If it compiled, try to run it in the simulator
        # We will retry with increasing timeouts if it hangs
        run_success = False
        run_output = ""
        timed_out = False
        current_timeout = timeout_sec
        
        for sim_attempt in range(3):
            success, output, t_out = run_in_simulator(
                elf_file=elf_file,
                toolchain=args.toolchain,
                binaries=TOOLCHAIN_BINARIES,
                timeout_sec=current_timeout,
            )
            run_output = output
            if not t_out:
                run_success = success
                timed_out = False
                break
            else:
                print(f"[Simulator] Timed out after {current_timeout}s. Retrying with longer timeout...")
                current_timeout *= 2
                timed_out = True
                
        if timed_out:
            entry["run_success"] = False
            entry["run_output"] = RunHistory.lines(run_output)
            entry["timed_out"] = True
            entry["attempt_result"] = "run_timed_out"
            run_history.flush()
            print(f"[Loop] Code consistently timed out. Feeding back to agent...")
            last_attempt_feedback = (
                f"Simulator output before timeout in {board_name}:\n"
                f"{run_output}"
            )
            if args.incremental:
                current_prompt = build_patch_retry_prompt(
                    current_source,
                    (
                        f"The code compiled successfully, but running it in {board_name} timed out after multiple attempts.\n"
                        f"Output before timeout:\n{run_output}\n\n"
                        "Ensure you are not stuck in an infinite loop before printing the required output. Please fix the logic."
                    )
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
        
        # 5. Check strictly for the expected unique string to avoid FVP boot log false positives
        if not run_success or args.expected not in run_output:
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
            if args.incremental:
                current_prompt = build_patch_retry_prompt(
                    current_source,
                    (
                        "The code compiled successfully and completed, but the expected output was not found.\n"
                        f"Output:\n{run_output}\n\n"
                        f"We expect the exact string '{args.expected}' to be printed to the UART. Please fix the logic."
                    )
                )
                response_mode = "patch"
            else:
                current_prompt = (
                    "The code compiled successfully and completed, but the expected output was not found.\n"
                    f"Output:\n{run_output}\n\n"
                    f"We expect the exact string '{args.expected}' to be printed to the UART. "
                    "Please fix the logic and return ONLY the corrected assembly/C code."
                )
                response_mode = "full_source"
            continue
            
        # 6. Success!
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
        print(f"\n=== FAILED: Agent could not fix the code after {MAX_RETRIES} attempts ===")

    print(f"\n[Info] Final run history saved to {history_file}")

if __name__ == "__main__":
    main()
