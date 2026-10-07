#!/bin/sh
# Usage: sh scripts/gcc_reference.sh [state] [outdir]
# Description: Build the gcc reference for the RV32I solver: the freestanding C
#              version compiled with the flags the assignment names, linked
#              against the same generated move tables as the assembly.
# Input: optional 14-digit state (default 21345671111111); extra compiler
#        flags can be passed in the CFLAGS_EXTRA environment variable
# Output: <outdir>/ref.elf, <outdir>/ref.dis; prints section sizes and checks
#         that no compiler helper (__mulsi3, __divsi3, ...) was linked in
# Dependencies: riscv64-unknown-elf-gcc (sudo apt install gcc-riscv64-unknown-elf)
set -e
STATE="${1:-21345671111111}"
OUT="${2:-build/gcc_ref}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$OUT"
{   # export the table labels and drop the LED-only tables
    printf '.globl perm_mv_R\n.globl twist_mv_R\n.globl turn_src\n.globl turn_add\n'
    sed '/^# RENDER_BEGIN/,/^# RENDER_END/d' "$ROOT/src/tables.s"
} > "$OUT/tables_ref.s"
riscv64-unknown-elf-gcc -O2 -march=rv32i -mabi=ilp32 -ffreestanding -nostdlib \
    -Wall -Wextra -Wl,--no-relax -T "$ROOT/src/rv32.ld" -DSTATE="\"$STATE\"" \
    $CFLAGS_EXTRA -o "$OUT/ref.elf" "$ROOT/src/ida_star_rv32.c" "$OUT/tables_ref.s"
riscv64-unknown-elf-objdump -d "$OUT/ref.elf" > "$OUT/ref.dis"
riscv64-unknown-elf-size -A "$OUT/ref.elf" | grep -E '^\.(text|rodata|data|bss)'
if grep -qE '__(mul|div|udiv|mod|umod)[sd]i3|\b(mul|div|rem)[a-z]*\b' "$OUT/ref.dis"; then
    echo "ERROR: multiply/divide found in the reference build"; exit 1
fi
echo "no multiply/divide instructions or helpers: OK"
