import os
import sys
from agent.bootstrap import build_loop_config
from agent.cli import check_git_status, parse_args
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

def main():
    args = parse_args()

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
