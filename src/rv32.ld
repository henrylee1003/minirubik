/* Ripes memory map: code at 0x0, data at 0x10000000. */
ENTRY(_start)
SECTIONS
{
    . = 0x0;
    .text : { *(.text.startup._start) *(.text._start) *(.text*) }
    . = 0x10000000;
    .rodata : { *(.rodata*) *(.srodata*) }
    .data : { *(.data*) *(.sdata*) }
    .bss : { *(.bss*) *(.sbss*) *(COMMON) }
    /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.note*) *(.eh_frame*) }
}
