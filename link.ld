ENTRY(_start)

MEMORY {
    /* QEMU versatilepb board has 128MB RAM starting at 0x00000000 */
    RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 128M
}

SECTIONS {
    . = 0x10000; /* Start offset, commonly used for versatilepb kernels */

    .text : {
        *(.text)
    } > RAM

    .data : {
        *(.data)
    } > RAM

    .bss : {
        *(.bss COMMON)
    } > RAM

    /* Set up stack pointer at top of RAM */
    . = ALIGN(8);
    . = . + 0x1000; /* 4KB Stack */
    stack_top = .;
}
