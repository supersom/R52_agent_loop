Write ARM AArch32 assembly for {board_name} that computes an 8-bit XOR checksum and prints it as uppercase hex.

This task is intentionally MULTI-FILE. Implement it using at least these files under the active output folder:
- `agent_code.s` (entry point)
- `lib/uart_io.inc` (UART helpers)
- `lib/hex.inc` (hex formatting helper)

Functional requirements:
- Use `_start` as entry point in `agent_code.s`.
- Define this byte array and compute XOR at runtime: `0x12, 0x34, 0x56, 0x78, 0x9A`.
- Convert the checksum to exactly 2 uppercase hex digits.
- Print the exact string `{expected_output}`.
- Write characters to UART data register at `{uart_addr}`.
- Halt/exit cleanly for simulation (no infinite loop hang).

Structure requirements:
- `agent_code.s` must include and call helpers from `lib/uart_io.inc` and `lib/hex.inc`.
- `lib/uart_io.inc` should contain reusable routines/macros for byte/string UART output.
- `lib/hex.inc` should contain logic to convert one byte to two uppercase hex ASCII chars.
- Keep responsibilities separated: checksum logic in `agent_code.s`, UART/format helpers in include files.

Constraints:
- Do not hardcode checksum result digits.
- Keep code minimal but clear.
- If existing code is already close, change as little as possible while satisfying the multi-file split.
