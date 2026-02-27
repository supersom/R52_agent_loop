import subprocess
import os
import sys
import argparse
from agent.bootstrap import build_loop_config
from agent.loop import run_agent_loop
from agent.toolchain import (
    load_toolchain_binaries_from_env,
)
from agent.workspace import (
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

    try:
        loop_config = build_loop_config(
            args=args,
            workspace=WORKSPACE,
            code_root=CODE_ROOT,
            generated_source_name=GENERATED_SOURCE_NAME,
            generated_elf_name=GENERATED_ELF_NAME,
            max_retries=MAX_RETRIES,
            toolchain_binaries=TOOLCHAIN_BINARIES,
        )
    except FileNotFoundError as e:
        print(str(e))
        sys.exit(1)

    run_agent_loop(loop_config)

if __name__ == "__main__":
    main()
