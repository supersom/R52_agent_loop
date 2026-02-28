import argparse
import subprocess
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agentic ARM Development Loop")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Automatically proceed past the uncommitted-changes check",
    )
    parser.add_argument(
        "--toolchain",
        choices=["gcc", "ds5"],
        default="gcc",
        help="Toolchain to use (gcc or ds5)",
    )
    parser.add_argument(
        "--source",
        type=str,
        help="Path to an existing folder of code to start with.",
        default=None,
    )
    parser.add_argument(
        "--repo",
        type=str,
        help="Path to a repository to edit/verify in repo mode.",
        default=None,
    )
    parser.add_argument(
        "--entry-file",
        type=str,
        help="Primary editable file path (relative to output/repo dir).",
        default="agent_code.s",
    )
    parser.add_argument(
        "--build-cmd",
        type=str,
        help="Build command for repo mode (required when --repo is set).",
        default=None,
    )
    parser.add_argument(
        "--test-cmd",
        type=str,
        help="Optional test command for repo mode.",
        default=None,
    )
    parser.add_argument(
        "--verify-timeout",
        type=int,
        help="Timeout in seconds for each repo-mode verify command.",
        default=120,
    )
    parser.add_argument(
        "--prompt",
        type=str,
        help="Path to a custom prompt file in the prompts/ folder.",
        default="prompts/prime_sum.txt",
    )
    parser.add_argument(
        "--expected",
        type=str,
        help="Expected output string from the simulator.",
        default="SUM: 129",
    )
    parser.add_argument(
        "--incremental",
        nargs="?",
        const="normal",
        choices=["normal", "strict"],
        default=None,
        help=(
            "Use incremental JSON edit retries instead of full-source retries. "
            "Optional mode: 'strict' prevents fallback to full-source after edit-apply failures."
        ),
    )
    args = parser.parse_args()
    if args.repo and not args.build_cmd:
        parser.error("--build-cmd is required when --repo is set")
    if args.verify_timeout <= 0:
        parser.error("--verify-timeout must be > 0")
    return args


def check_git_status(auto_yes: bool = False) -> None:
    """
    Check if there are uncommitted changes. If so, ask the user if they want to proceed.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout.strip():
            print("\n[Warning] You have uncommitted changes in your repository:")
            print(result.stdout)
            if auto_yes:
                print("[Info] Proceeding because --yes/-y was provided.")
                return
            choice = input("Do you really want to proceed? (y/N): ").strip().lower()
            if choice != "y":
                print("Aborting.")
                sys.exit(0)
    except subprocess.CalledProcessError:
        pass
