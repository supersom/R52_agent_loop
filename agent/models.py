from dataclasses import dataclass

from agent.toolchain import ToolchainBinaries


@dataclass(frozen=True)
class LoopConfig:
    toolchain: str
    incremental: bool
    expected_output: str
    board_name: str
    code_dir: str
    source_file: str
    elf_file: str
    history_file: str
    initial_prompt: str
    task_contract_prompt: str
    workspace: str
    toolchain_binaries: ToolchainBinaries
    max_retries: int
    timeout_sec: int = 2
