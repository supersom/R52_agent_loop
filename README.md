# R52 Agent Loop

Agentic bare-metal ARM development loop that:

- asks an LLM (currently the local `gemini` CLI) to generate ARM assembly
- compiles the result (`arm-none-eabi-gcc` or Arm DS-5 toolchain)
- runs it in a simulator (QEMU or Arm FVP Cortex-R52)
- retries with compiler/runtime feedback until the expected UART output is produced

## What It Does

`orchestrator.py` runs an iterative write-build-run loop (up to 5 attempts) for assembly tasks defined in `prompts/`.

Default task:
- generate a program that prints `SUM: 129` (sum of first 10 primes) via UART

Alternate example:
- `prompts/fibonacci.txt` (prints a Fibonacci result string)

## Requirements

Required for the default `gcc` path:
- `python3`
- `gemini` CLI (available on `PATH`)
- `arm-none-eabi-gcc`
- `qemu-system-arm`

Optional for `ds5` path:
- Arm Development Studio / Arm Compiler 6 binaries at the hardcoded paths in `orchestrator.py`
- FVP BaseR Cortex-R52

Optional helper:
- `jq` (for `view_run_history.sh`)

## Configuration (.env / Environment Variables)

For the `ds5` toolchain path, `orchestrator.py` can read binary locations from a local `.env` file or from environment variables.

Supported variables:
- `ARMCLANG_BIN`
- `ARMLINK_BIN`
- `FVP_BIN`

Precedence:
- existing environment variables
- `.env` values in the project root
- built-in defaults (the current hardcoded paths)

Example `.env`:

```bash
ARMCLANG_BIN=/opt/arm/developmentstudio-2025.0-1/sw/ARMCompiler6.24/bin/armclang
ARMLINK_BIN=/opt/arm/developmentstudio-2025.0-1/sw/ARMCompiler6.24/bin/armlink
FVP_BIN=/opt/arm/developmentstudio-2025.0-1/bin/FVP_BaseR_Cortex-R52
```

## Usage

Run the default prime-sum prompt with GCC + QEMU:

```bash
python3 orchestrator.py
```

Run the Fibonacci prompt:

```bash
python3 orchestrator.py --prompt prompts/fibonacci.txt --expected "FIB: 5"
```

Use the DS-5/FVP toolchain path:

```bash
python3 orchestrator.py --toolchain ds5
```

Seed the prompt with an existing codebase for incremental changes:

```bash
python3 orchestrator.py --source /path/to/codebase
```

Use strict incremental mode (never fall back to full-source retries after edit-apply failures):

```bash
python3 orchestrator.py --incremental strict
```

## CLI Options

- `--toolchain {gcc,ds5}`: compile/run path (`gcc` default)
- `--source <dir>`: include existing code files (`.c`, `.h`, `.s`, `.S`, `.ld`, `Makefile`) in the LLM prompt
- `--prompt <path>`: prompt template path (default `prompts/prime_sum.txt`)
- `--expected <string>`: required output substring checked in simulator output (default `SUM: 129`)
- `--incremental [normal|strict]`: use incremental JSON edit retries (`--incremental` == `normal`; `strict` prevents fallback to full-source on edit-apply failures)
  - Incremental JSON edits now support path-aware multi-file operations under the active output folder (`path`, `new_path`, `create_file`, `delete_file`, `move_file`).

## Files

- `orchestrator.py`: main agent loop
- `prompts/prime_sum.txt`: default task prompt template
- `prompts/fibonacci.txt`: alternate task prompt template
- `link.ld`: linker script used by the GCC flow
- `view_run_history.sh`: pretty-print helper for `run_history.json` using `jq`

Generated/local artifacts (ignored by git):
- `agent_code.s`, `agent_code.o`, `agent_code.elf`
- `current_prompt.txt`
- `run_history.json`
- `llm_debug.log`

## Notes

- The script writes the full prompt to `current_prompt.txt` and appends Gemini debug stderr to `llm_debug.log`.
- Run history is saved after each LLM attempt in `run_history.json`, including prompt, generated code, and diff from the previous attempt.
- DS-5/FVP paths can now be overridden with `.env` or environment variables; if none are set, the script uses the built-in defaults.
