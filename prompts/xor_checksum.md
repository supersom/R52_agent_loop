Write ARM AArch32 assembly for {board_name} that computes the XOR checksum of a fixed byte array and prints the result.

Requirements:
- Use ARM assembly source (`.s`) with `_start` as the entry point.
- Define this byte array in memory: 0x12, 0x34, 0x56, 0x78
- Iterate over the bytes and compute the XOR checksum.
- Convert the 8-bit checksum to exactly 2 uppercase hexadecimal digits (with leading zero if needed).
- Print the exact string: {expected_output}
- Print to UART0 data register at {uart_addr}
- Halt/exit cleanly for the simulator.

Notes:
- The checksum must be computed from the bytes in code (do not hardcode the result digits).
- Use byte loads/stores where appropriate for array access / string construction.

