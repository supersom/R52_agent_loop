Write ARM AArch32 assembly for {board_name} that reverses a string into a .data buffer and prints it.

Requirements:
- Use ARM assembly source (`.s`) with `_start` as the entry point.
- Source string must be "R52".
- Reverse the string into a writable buffer in `.data`.
- Construct the final output string in a `.data` buffer and print the exact string: {expected_output}
- Print to UART0 data register at {uart_addr}
- Also use semihosting console output so the result is visible in simulation logs.
- Halt/exit cleanly for the simulator.

Notes:
- The reversed result must be computed in code (do not hardcode the final output string).
- Use byte loads/stores for string processing and buffer writes.
