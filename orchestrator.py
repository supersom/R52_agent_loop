import subprocess
import os
import sys
import argparse
from agent.loop import run_agent_loop
from agent.models import LoopConfig
from agent.prompting import (
    build_task_contract_prompt,
)
from agent.toolchain import (
    get_target_details,
    load_toolchain_binaries_from_env,
)
from agent.workspace import (
    collect_existing_code_context,
    get_prompt_run_dir,
    load_dotenv,
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
    loop_config = LoopConfig(
        toolchain=args.toolchain,
        incremental=args.incremental,
        expected_output=args.expected,
        board_name=board_name,
        code_dir=code_dir,
        source_file=source_file,
        elf_file=elf_file,
        history_file=history_file,
        initial_prompt=initial_prompt,
        task_contract_prompt=task_contract_prompt,
        workspace=WORKSPACE,
        toolchain_binaries=TOOLCHAIN_BINARIES,
        max_retries=MAX_RETRIES,
    )
    run_agent_loop(loop_config)

if __name__ == "__main__":
    main()
