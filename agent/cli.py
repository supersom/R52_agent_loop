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
        action="store_true",
        help="Use incremental patch retries (unified diff) instead of full-source retries",
    )
    return parser.parse_args()


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
