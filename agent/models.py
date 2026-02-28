from dataclasses import dataclass

from agent.toolchain import ToolchainBinaries


@dataclass(frozen=True)
class LoopConfig:
    toolchain: str
    incremental: bool
    incremental_strict: bool
    repo_mode: bool
    repo_dir: str | None
    entry_file_rel: str
    build_cmd: str | None
    test_cmd: str | None
    verify_timeout_sec: int
    expected_output: str
    board_name: str
    edit_dir: str
    run_dir: str
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
