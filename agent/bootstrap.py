import os
from argparse import Namespace

from agent.constants import (
    CODE_ROOT,
    GENERATED_ELF_NAME,
    GENERATED_SOURCE_NAME,
    MAX_RETRIES,
    WORKSPACE,
)
from agent.models import LoopConfig
from agent.prompting import build_repo_task_contract_prompt, build_task_contract_prompt
from agent.toolchain import ToolchainBinaries, get_target_details
from agent.workspace import collect_existing_code_context, get_prompt_run_dir


def build_loop_config(
    *,
    args: Namespace,
    toolchain_binaries: ToolchainBinaries,
) -> LoopConfig:
    incremental_mode = args.incremental
    incremental_enabled = incremental_mode is not None
    incremental_strict = incremental_mode == "strict"
    repo_mode = args.repo is not None

    uart_addr, board_name = get_target_details(args.toolchain)
    source_context_dir = args.repo if repo_mode else args.source
    existing_code_context = collect_existing_code_context(source_context_dir)

    prompt_path = os.path.join(WORKSPACE, args.prompt)
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Error: Prompt file not found at {prompt_path}")

    with open(prompt_path, "r") as f:
        base_prompt_text = f.read()

    if repo_mode:
        repo_dir = os.path.abspath(args.repo)
        if not os.path.isdir(repo_dir):
            raise FileNotFoundError(f"Error: Repo directory not found at {repo_dir}")
        code_dir = repo_dir
        entry_file_rel = os.path.normpath(args.entry_file)
        if entry_file_rel.startswith("..") or os.path.isabs(entry_file_rel):
            raise ValueError("Error: --entry-file must be a relative path inside --repo")
        source_file = os.path.join(code_dir, entry_file_rel)
        history_dir = os.path.join(code_dir, ".agent_loop")
        os.makedirs(history_dir, exist_ok=True)
        history_file = os.path.join(history_dir, "run_history.json")
    else:
        code_dir = get_prompt_run_dir(CODE_ROOT, prompt_path)
        os.makedirs(code_dir, exist_ok=True)
        entry_file_rel = GENERATED_SOURCE_NAME
        source_file = os.path.join(code_dir, GENERATED_SOURCE_NAME)
        history_file = os.path.join(code_dir, "run_history.json")

    elf_file = os.path.join(code_dir, GENERATED_ELF_NAME)

    print(f"[Info] Prompt outputs will be written to {code_dir}")

    formatted_prompt = base_prompt_text.format(
        uart_addr=uart_addr,
        board_name=board_name,
        expected_output=args.expected,
    )
    if repo_mode:
        task_contract_prompt = build_repo_task_contract_prompt(
            prompt_name=os.path.basename(prompt_path),
            repo_dir=code_dir,
            entry_file_rel=entry_file_rel,
            build_cmd=args.build_cmd,
            test_cmd=args.test_cmd,
            formatted_prompt=formatted_prompt,
        )
    else:
        task_contract_prompt = build_task_contract_prompt(
            prompt_name=os.path.basename(prompt_path),
            toolchain=args.toolchain,
            board_name=board_name,
            uart_addr=uart_addr,
            expected_output=args.expected,
            formatted_prompt=formatted_prompt,
        )

    initial_prompt = (
        "CRITICAL: If an incremental feature is requested and there is existing code that met requirements prior to this incremental feature request, try to change that existing code as little as possible while implementing this feature. If you would like to improve on something that existed, jot that down in a comments and allow the developer to decide. "
        "CRITICAL: If you start off with non-empty code, first check if that meets requirements before attempting to modify. You might not have to run this through an iteration of write-build-run - the requirements might be so different from the existing code that it is obvious that it has to be rewritten."
        f"{existing_code_context}"
    )

    return LoopConfig(
        toolchain=args.toolchain,
        incremental=incremental_enabled,
        incremental_strict=incremental_strict,
        repo_mode=repo_mode,
        repo_dir=code_dir if repo_mode else None,
        entry_file_rel=entry_file_rel,
        build_cmd=args.build_cmd,
        test_cmd=args.test_cmd,
        verify_timeout_sec=args.verify_timeout,
        expected_output=args.expected,
        board_name=board_name,
        code_dir=code_dir,
        source_file=source_file,
        elf_file=elf_file,
        history_file=history_file,
        initial_prompt=initial_prompt,
        task_contract_prompt=task_contract_prompt,
        workspace=WORKSPACE,
        toolchain_binaries=toolchain_binaries,
        max_retries=MAX_RETRIES,
    )
