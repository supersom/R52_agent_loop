import os
import shutil
from datetime import datetime


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


def get_prompt_run_dir(code_root: str, prompt_path: str) -> str:
    """
    Resolve the working output directory for a prompt file.
    Example: prompts/prime_sum.txt -> ./code/prime_sum
    """
    prompt_name = os.path.splitext(os.path.basename(prompt_path))[0]
    return os.path.join(code_root, prompt_name)


def snapshot_successful_run(code_dir: str) -> str:
    """
    Copy top-level generated files from the active prompt directory into a timestamped snapshot.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    snapshot_dir = os.path.join(code_dir, timestamp)
    os.makedirs(snapshot_dir, exist_ok=False)

    for name in os.listdir(code_dir):
        src_path = os.path.join(code_dir, name)
        if os.path.isfile(src_path):
            shutil.copy2(src_path, os.path.join(snapshot_dir, name))

    return snapshot_dir


def collect_existing_code_context(source_dir: str | None) -> str:
    """
    Read supported source files from a seed folder and return a prompt-ready block.
    """
    if not source_dir or not os.path.isdir(source_dir):
        return ""

    context = ""
    print(f"--- Reading existing code from {source_dir} ---")
    for root, _, files in os.walk(source_dir):
        for file_name in files:
            if not file_name.endswith((".c", ".h", ".s", ".S", ".ld", "Makefile")):
                continue
            file_path = os.path.join(root, file_name)
            try:
                with open(file_path, "r") as f:
                    content = f.read()
                context += f"\n\n--- File: {file_path} ---\n```\n{content}\n```\n"
            except OSError as e:
                print(f"Failed to read {file_path}: {e}")

    if context:
        return "\n\n=== EXISTING CODEBASE ===\n" + context + "\n=========================\n"
    return ""
