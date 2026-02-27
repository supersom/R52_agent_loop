Write ARM AArch32 assembly for {board_name} that formats a 32-bit value as uppercase hexadecimal and prints it.

Requirements:
- Use ARM assembly source (`.s`) with `_start` as the entry point.
- Use the constant value 0xDEADBEEF.
- Convert it to exactly 8 uppercase hexadecimal digits.
- Print the exact string: {expected_output}
- Print to UART0 data register at {uart_addr}
- Halt/exit cleanly for the simulator.

Notes:
- Compute the hex digits in code (do not hardcode "DEADBEEF" as the printed result).
- Use nibble extraction and ASCII conversion logic.
