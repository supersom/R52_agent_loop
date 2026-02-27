import os
from argparse import Namespace

from agent.models import LoopConfig
from agent.prompting import build_task_contract_prompt
from agent.toolchain import ToolchainBinaries, get_target_details
from agent.workspace import collect_existing_code_context, get_prompt_run_dir


def build_loop_config(
    *,
    args: Namespace,
    workspace: str,
    code_root: str,
    generated_source_name: str,
    generated_elf_name: str,
    max_retries: int,
    toolchain_binaries: ToolchainBinaries,
) -> LoopConfig:
    uart_addr, board_name = get_target_details(args.toolchain)
    existing_code_context = collect_existing_code_context(args.source)

    prompt_path = os.path.join(workspace, args.prompt)
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Error: Prompt file not found at {prompt_path}")

    with open(prompt_path, "r") as f:
        base_prompt_text = f.read()

    code_dir = get_prompt_run_dir(code_root, prompt_path)
    os.makedirs(code_dir, exist_ok=True)
    source_file = os.path.join(code_dir, generated_source_name)
    elf_file = os.path.join(code_dir, generated_elf_name)
    history_file = os.path.join(code_dir, "run_history.json")

    print(f"[Info] Prompt outputs will be written to {code_dir}")

    formatted_prompt = base_prompt_text.format(
        uart_addr=uart_addr,
        board_name=board_name,
        expected_output=args.expected,
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
        "CRITICAL: If an incremental feature is requested and there is existing code that met requirements prior to this incremental feature request, try to change that existing code as little as possible while implementing this feature. If you would like to improve on something that existed, jot that down in a comments and allow the developer to decide. "
        "CRITICAL: If you start off with non-empty code, first check if that meets requirements before attempting to modify. You might not have to run this through an iteration of write-build-run - the requirements might be so different from the existing code that it is obvious that it has to be rewritten."
        f"{existing_code_context}"
    )

    return LoopConfig(
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
        workspace=workspace,
        toolchain_binaries=toolchain_binaries,
        max_retries=max_retries,
    )
