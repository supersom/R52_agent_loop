import subprocess
import os
import sys
import json
import time
import argparse
import difflib
import shutil
from datetime import datetime

# You can use the `google-genai` package or direct API calls for the LLM part later.
# For now, we stub out the LLM call.

MAX_RETRIES = 5
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILE = os.path.join(WORKSPACE, "agent_code.s")
ELF_FILE = os.path.join(WORKSPACE, "agent_code.elf")
OBJ_FILE = os.path.join(WORKSPACE, "agent_code.o")

def load_dotenv(dotenv_path: str) -> None:
    """
    Load simple KEY=VALUE pairs from a .env file into os.environ.
    Existing environment variables are preserved.
    """
    if not os.path.exists(dotenv_path):
        return

    try:
        with open(dotenv_path, "r") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                if not key:
                    continue

                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]

                os.environ.setdefault(key, value)
    except OSError as e:
        print(f"[Config] Warning: Could not read {dotenv_path}: {e}")

load_dotenv(os.path.join(WORKSPACE, ".env"))

# DS-5 / ARMCompiler6 paths
ARMCLANG_BIN = os.environ.get(
    "ARMCLANG_BIN",
    "/opt/arm/developmentstudio-2025.0-1/sw/ARMCompiler6.24/bin/armclang"
)
ARMLINK_BIN = os.environ.get(
    "ARMLINK_BIN",
    "/opt/arm/developmentstudio-2025.0-1/sw/ARMCompiler6.24/bin/armlink"
)
FVP_BIN = os.environ.get(
    "FVP_BIN",
    "/opt/arm/developmentstudio-2025.0-1/bin/FVP_BaseR_Cortex-R52"
)

def call_llm(prompt: str, code_dir: str) -> str:
    """
    Calls the local `gemini` CLI to generate the code.
    """
    print(f"\n[LLM] Generating code... (Prompt length: {len(prompt)})")
    print(f"[LLM] --- Prompt Sent ---\n{prompt}\n-----------------------")
    
    # We write the prompt to a temp file to avoid command-line length limits
    prompt_file = os.path.join(code_dir, "current_prompt.txt")
    with open(prompt_file, "w") as f:
        f.write(prompt)
        
    try:
        # We pass the prompt as the positional argument.
        # We also pass -y to make it one-shot and --model to ensure it uses the right model.
        print(f"[LLM] --- Streaming Response (Debug logs routed to {os.path.join(code_dir, 'llm_debug.log')}) ---")
        debug_log_path = os.path.join(code_dir, "llm_debug.log")
        
        with open(debug_log_path, "a") as debug_file:
            debug_file.write(f"\n\n--- New Prompt Execution (Length: {len(prompt)}) ---\n")
            process = subprocess.Popen(
                ["gemini", "-d", prompt], # Enable debug logs
                stdout=subprocess.PIPE,
                stderr=debug_file, # Route stderr directly to the log file
                text=True,
                bufsize=1
            )
            
            response_lines = []
            for line in iter(process.stdout.readline, ''):
                sys.stdout.write(line)
                sys.stdout.flush()
                response_lines.append(line)
                
            process.stdout.close()
            process.wait()
            
        if process.returncode != 0:
            print(f"[LLM] Error calling Gemini CLI. Check {debug_log_path} for details.")
            return "    .global _start\n_start:\n    mov r0, #42\n"
            
        response = "".join(response_lines)
        
        # The LLM often wraps code in markdown blocks like ```assembly or ```c
        # We should try to strip those out so the compiler doesn't choke.
        lines = response.split('\n')
        code_lines = []
        in_code_block = False
        
        for line in lines:
            if line.startswith('```'):
                in_code_block = not in_code_block
                continue
            if in_code_block or not any(l.startswith('```') for l in lines):
                code_lines.append(line)
                
        final_code = '\n'.join(code_lines)
        print(f"[LLM] --- Code Received ---\n{final_code}\n---------------------------")
        return final_code
        
    except subprocess.CalledProcessError as e:
        print(f"[LLM] Error calling Gemini CLI: {e.stderr}")
        return "    .global _start\n_start:\n    mov r0, #42\n"

def compile_code(source_file, elf_file, toolchain, code_dir):
    """
    Compile the generated code.
    Returns (success: bool, error_message: str)
    """
    print(f"\n[Compiler] Compiling {source_file} using {toolchain}...")
    obj_file = os.path.join(code_dir, "agent_code.o")
    
    if toolchain == "ds5":
        # ARM Compiler 6 (armclang + armlink)
        compile_cmd = [
            ARMCLANG_BIN,
            "--target=arm-arm-none-eabi",
            "-mcpu=cortex-r52",
            "-O0", "-c",
            source_file,
            "-o", obj_file
        ]
        link_cmd = [
            ARMLINK_BIN,
            "--ro-base=0x00000000",
            "--entry=_start",
            obj_file,
            "-o", elf_file
        ]
        
        try:
            subprocess.run(compile_cmd, capture_output=True, text=True, check=True)
            subprocess.run(link_cmd, capture_output=True, text=True, check=True)
            print("[Compiler] Success!")
            return True, ""
        except subprocess.CalledProcessError as e:
            print("[Compiler] Failed!")
            return False, e.stderr

    else:
        # Default gcc
        cmd = [
            "arm-none-eabi-gcc",
            "-O0", "-nostdlib",
            "-T", os.path.join(WORKSPACE, "link.ld"),
            source_file,
            "-o", elf_file
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            print("[Compiler] Success!")
            return True, ""
        except subprocess.CalledProcessError as e:
            print("[Compiler] Failed!")
            return False, e.stderr

def run_in_simulator(elf_file, toolchain, timeout_sec=5):
    """
    Run the compiled binary in the simulator (QEMU or FVP).
    Returns (success: bool, output: str, timed_out: bool)
    """
    print(f"\n[Simulator] Running {elf_file} using {toolchain} (Timeout: {timeout_sec}s)...")
    
    if toolchain == "ds5":
        # FVP
        cmd = [
            FVP_BIN,
            "-C", "cluster0.NUM_CORES=1",
            "--application", elf_file
        ]
    else:
        # Default QEMU
        cmd = [
            "qemu-system-arm",
            "-M", "versatilepb",
            "-m", "128M",
            "-nographic",
            "-kernel", elf_file
        ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        output = result.stdout + result.stderr
        print("[Simulator] Finished Execution naturally.")
        return True, output, False
    except subprocess.TimeoutExpired as e:
        output = str(e.stdout or "") + str(e.stderr or "")
        print(f"[Simulator] Timeout! Execution exceeded {timeout_sec} seconds.")
        return True, output, True
    except Exception as e:
        return False, str(e), False

def check_git_status():
    """
    Check if there are uncommitted changes. If so, ask the user if they want to proceed.
    """
    try:
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=True)
        if result.stdout.strip():
            print("\n[Warning] You have uncommitted changes in your repository:")
            print(result.stdout)
            choice = input("Do you really want to proceed? (y/N): ").strip().lower()
            if choice != 'y':
                print("Aborting.")
                sys.exit(0)
    except subprocess.CalledProcessError:
        pass # Not a git repo or git not installed

def main():
    check_git_status()
    
    parser = argparse.ArgumentParser(description="Agentic ARM Development Loop")
    parser.add_argument("--toolchain", choices=["gcc", "ds5"], default="gcc", help="Toolchain to use (gcc or ds5)")
    parser.add_argument("--source", type=str, help="Path to an existing folder of code to start with.", default=None)
    parser.add_argument("--prompt", type=str, help="Path to a custom prompt file in the prompts/ folder.", default="prompts/prime_sum.txt")
    parser.add_argument("--expected", type=str, help="Expected output string from the simulator.", default="SUM: 129")
    args = parser.parse_args()

    print(f"=== Starting Agentic ARM Development Loop (Toolchain: {args.toolchain}) ===")
    
    # We tweak the prompt slightly based on the toolchain/board
    uart_addr = "0x101F1000" if args.toolchain == "gcc" else "0x9C090000" # FVP BaseR UART0 is typically at 0x9C090000
    board_name = "QEMU versatilepb" if args.toolchain == "gcc" else "FVP Cortex-R52"
    
    # If a source directory is provided, read all relevant source files
    existing_code_context = ""
    if args.source and os.path.isdir(args.source):
        print(f"--- Reading existing code from {args.source} ---")
        for root, _, files in os.walk(args.source):
            for file in files:
                if file.endswith(('.c', '.h', '.s', '.S', '.ld', 'Makefile')):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r') as f:
                            content = f.read()
                            existing_code_context += f"\n\n--- File: {file_path} ---\n```\n{content}\n```\n"
                    except Exception as e:
                        print(f"Failed to read {file_path}: {e}")
                        
        if existing_code_context:
            existing_code_context = "\n\n=== EXISTING CODEBASE ===\n" + existing_code_context + "\n=========================\n"

    # Read the prompt file
    prompt_path = os.path.join(WORKSPACE, args.prompt)
    if not os.path.exists(prompt_path):
        print(f"Error: Prompt file not found at {prompt_path}")
        sys.exit(1)
        
    with open(prompt_path, 'r') as f:
        base_prompt_text = f.read()

    # Format the dynamic parts of the prompt
    formatted_prompt = base_prompt_text.format(
        uart_addr=uart_addr,
        board_name=board_name,
        expected_output=args.expected
    )

    initial_prompt = (
        f"{formatted_prompt}\n"
        f"CRITICAL: If an incremental feature is requested and there is existing code that met requirements prior to this incremental feature request, try to change that existing code as little as possible while implementing this feature. If you would like to improve on something that existed, jot that down in a comments and allow the developer to decide. "
        f"CRITICAL: If you start off with non-empty code, first check if that meets requirements before attempting to modify. You might not have to run this through an iteration of write-build-run - the requirements might be so different from the existing code that it is obvious that it has to be rewritten."
        f"{existing_code_context}"
    )
    
    current_prompt = initial_prompt
    timeout_sec = 2
    
    history = []
    previous_code = existing_code_context if existing_code_context else ""
    
    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n--- Attempt {attempt}/{MAX_RETRIES} ---")
        
        # 1. Ask the Agent to write/fix the code
        generated_code = call_llm(current_prompt)
        
        # Compute diff
        diff = list(difflib.unified_diff(
            previous_code.splitlines(keepends=True),
            generated_code.splitlines(keepends=True),
            fromfile=f"Attempt_{attempt-1}",
            tofile=f"Attempt_{attempt}"
        ))
        diff_str = "".join(diff)
        
        # Save to history
        history.append({
            "attempt": attempt,
            "prompt": current_prompt,
            "generated_code": generated_code,
            "diff": diff_str
        })
        
        # Dump run history to JSON immediately after LLM response
        history_file = os.path.join(WORKSPACE, "run_history.json")
        with open(history_file, "w") as f:
            json.dump(history, f, indent=4)
        
        previous_code = generated_code
        
        # 2. Save it to disk
        with open(SOURCE_FILE, "w") as f:
            f.write(generated_code)
            
        # 3. Try to compile it
        compile_success, compile_error = compile_code(SOURCE_FILE, ELF_FILE, args.toolchain)
        
        if not compile_success:
            print(f"[Loop] Compilation failed. Feeding error back to agent...")
            current_prompt = (
                f"Your previous code failed to compile with the following error:\n"
                f"{compile_error}\n\n"
                f"Please fix the code and return ONLY the corrected assembly/C code."
            )
            continue # Try again!
            
        # 4. If it compiled, try to run it in the simulator
        # We will retry with increasing timeouts if it hangs
        run_success = False
        run_output = ""
        timed_out = False
        current_timeout = timeout_sec
        
        for sim_attempt in range(3):
            success, output, t_out = run_in_simulator(ELF_FILE, args.toolchain, current_timeout)
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
            print(f"[Loop] Code consistently timed out. Feeding back to agent...")
            current_prompt = (
                f"The code compiled successfully, but running it in {board_name} timed out after multiple attempts.\n"
                f"Output before timeout:\n{run_output}\n\n"
                f"Ensure you are not stuck in an infinite loop before printing the required output. Please fix the logic and try again."
            )
            continue
        
        # 5. Check strictly for the expected unique string to avoid FVP boot log false positives
        if not run_success or args.expected not in run_output:
            print(f"[Loop] Runtime failed or output was incorrect. Output:\n{run_output}")
            current_prompt = (
                f"The code compiled successfully and completed, but the expected output was not found.\n"
                f"Output:\n{run_output}\n\n"
                f"We expect the exact string '{args.expected}' to be printed to the UART. Please fix the logic and try again."
            )
            continue
            
        # 6. Success!
        print("\n=== SUCCESS! The agent wrote working ARM code! ===")
        print("Final Output:\n", run_output)
        break
    else:
        print(f"\n=== FAILED: Agent could not fix the code after {MAX_RETRIES} attempts ===")

    print(f"\n[Info] Final run history saved to {os.path.join(WORKSPACE, 'run_history.json')}")

if __name__ == "__main__":
    main()
