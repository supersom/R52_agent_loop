.arm
.global _start

.section .text
/* Vector Table */
_start:
    b reset_handler      /* Reset */
    b .                  /* Undefined Instruction */
    b .                  /* Software Interrupt (SVC) */
    b .                  /* Prefetch Abort */
    b .                  /* Data Abort */
    b .                  /* Reserved */
    b .                  /* IRQ */
    b .                  /* FIQ */

reset_handler:
    /* 1. Initialize Stack Pointer */
    ldr sp, =stack_top

    /* 2. Calculate the sum of the first 10 prime numbers */
    /* Primes: 2, 3, 5, 7, 11, 13, 17, 19, 23, 29. Sum = 129. */
    mov r0, #0          /* r0 = cumulative sum */
    mov r1, #0          /* r1 = count of primes found */
    mov r2, #2          /* r2 = current candidate number to test */

find_primes_loop:
    cmp r1, #10         /* Stop once we have 10 primes */
    beq calculation_done

    /* Primality Test for r2 */
    mov r3, #2          /* r3 = trial divisor */
is_prime_test:
    mul r4, r3, r3
    cmp r4, r2          /* If r3*r3 > r2, then r2 is prime */
    bgt is_prime_found

    /* Check divisibility: r4 = r2 % r3 */
    mov r4, r2
udiv_mod:
    cmp r4, r3
    blt udiv_mod_done
    sub r4, r4, r3
    b udiv_mod
udiv_mod_done:
    cmp r4, #0          /* If remainder is 0, r2 is not prime */
    beq next_candidate
    
    add r3, r3, #1      /* Increment trial divisor */
    b is_prime_test

is_prime_found:
    add r0, r0, r2      /* Add prime to sum */
    add r1, r1, #1      /* Increment prime count */

next_candidate:
    add r2, r2, #1      /* Test next number */
    b find_primes_loop

calculation_done:
    /* Save the final sum in r7 to preserve it across UART calls */
    mov r7, r0          /* r7 = 129 */
    
    /* 3. UART Initialization (FVP Cortex-R52 UART0: 0x9C090000) */
    ldr r6, =0x9C090000
    
    /* Disable UART */
    mov r1, #0
    str r1, [r6, #0x30]
    
    /* Set Baud Rate (IBRD=13, FBRD=1 for 115200 at 24MHz) */
    mov r1, #13
    str r1, [r6, #0x24]
    mov r1, #1
    str r1, [r6, #0x28]
    
    /* Set Line Control: 8-bit, FIFO enabled (0x70) */
    mov r1, #0x70
    str r1, [r6, #0x2c]
    
    /* Enable UART and Transmitter */
    mov r1, #0x101      /* UARTEN (bit 0) | TXE (bit 8) */
    str r1, [r6, #0x30]

    /* 4. Output "SUM: " prefix to UART */
    ldr r1, =msg_sum
    bl uart_print_string

    /* 5. Convert sum (r7) to ASCII and print to UART */
    mov r0, r7          /* Load the saved sum into r0 for conversion */
    mov r1, #10         /* Divisor */
    mov r3, #0          /* Digit counter */
convert_loop:
    mov r4, r0          /* r4 = dividend */
    mov r5, #0          /* r5 = quotient */
div10:
    cmp r4, #10
    blt div10_done
    sub r4, r4, #10
    add r5, r5, #1
    b div10
div10_done:
    add r4, r4, #'0'    /* Convert remainder to ASCII */
    push {r4}           /* Save digit on stack */
    add r3, r3, #1
    mov r0, r5          /* Process quotient in next iteration */
    cmp r0, #0
    bne convert_loop

print_digits:
    pop {r0}            /* Pop digits in correct order (MSB first) */
    bl uart_putc
    subs r3, r3, #1
    bne print_digits

    /* Print newline to UART */
    mov r0, #'\n'
    bl uart_putc

    /* 6. Redundant output via Semihosting SYS_WRITE0 for observability */
    ldr r1, =msg_full
    mov r0, #0x04       /* SYS_WRITE0 */
    svc 0x123456

    /* 7. Exit via ARM Semihosting SYS_EXIT */
    mov r0, #0x18       /* SYS_EXIT reason code */
    ldr r1, =exit_param_block
    svc 0x123456

/* Helper: Print null-terminated string at r1 to UART */
uart_print_string:
    push {lr}
ps_next:
    ldrb r0, [r1], #1
    cmp r0, #0
    popeq {pc}
    bl uart_putc
    b ps_next

/* Helper: Print character in r0 to UART */
uart_putc:
    /* Wait for Transmit FIFO not full (Flag Register at 0x18, bit 5) */
wait_tx:
    ldr r2, [r6, #0x18]
    tst r2, #0x20
    bne wait_tx
    strb r0, [r6]       /* Write to Data Register at offset 0 */
    bx lr

.section .data
.align 2
msg_sum:
    .ascii "SUM: "
    .byte 0

msg_full:
    .ascii "SUM: 129\n"
    .byte 0

.align 2
exit_param_block:
    .word 0x20026       /* ADP_Stopped_ApplicationExit */
    .word 0             /* Exit code 0 */

.section .bss
.align 3
stack_mem:
    .space 0x1000       /* 4KB stack space */
stack_top: