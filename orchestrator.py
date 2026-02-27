import sys
from agent.bootstrap import build_loop_config
from agent.cli import check_git_status, parse_args
from agent.constants import DOTENV_PATH
from agent.loop import run_agent_loop
from agent.toolchain import (
    load_toolchain_binaries_from_env,
)
from agent.workspace import (
    load_dotenv,
)

load_dotenv(DOTENV_PATH)
TOOLCHAIN_BINARIES = load_toolchain_binaries_from_env()

def main():
    args = parse_args()

    check_git_status(auto_yes=args.yes)

    print(f"=== Starting Agentic ARM Development Loop (Toolchain: {args.toolchain}, Incremental: {args.incremental}) ===")

    try:
        loop_config = build_loop_config(
            args=args,
            toolchain_binaries=TOOLCHAIN_BINARIES,
        )
    except FileNotFoundError as e:
        print(str(e))
        sys.exit(1)

    run_agent_loop(loop_config)

if __name__ == "__main__":
    main()
