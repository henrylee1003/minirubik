# Usage: python scripts/build_ripes.py [state] [output.s] [--no-render]
# Description: Join src/solver.s and src/tables.s into one file Ripes can open.
#              Optionally replace the built-in test table by one 14-digit state.
#              --no-render drops the LED renderer (CLI build for --iret).
# Input: optional 14-digit state (default: keep the three built-in test cases)
# Output: build/rubik_ripes.s, or build/rubik_cli.s with --no-render
# Dependencies: none (standard library only)
"""Build the single-file Ripes program."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOLVER = ROOT / "src" / "solver.s"
TABLES = ROOT / "src" / "tables.s"
DEFAULT_OUT = ROOT / "build" / "rubik_ripes.s"
TESTS_BLOCK = re.compile(r"(?<=^# TESTS_BEGIN\n).*?(?=^# TESTS_END\n)", re.M | re.S)
RENDER_BLOCK = re.compile(r"^# RENDER_BEGIN\n.*?^# RENDER_END\n", re.M | re.S)
TEST_SLOT = 20  # 1 expected-length byte + string + NUL + padding
ANY_LENGTH = 255


def test_entry(state: str, expected: int = ANY_LENGTH) -> str:
    """One 20-byte test case: expected length byte, state string, padding."""
    if '"' in state or "\\" in state or len(state) + 2 > TEST_SLOT:
        raise ValueError("state must be at most 18 plain characters")
    pad = TEST_SLOT - 1 - (len(state) + 1)
    lines = [f"    .byte {expected}", f'    .string "{state}"']
    if pad:
        lines.append(f"    .zero {pad}")
    return "\n".join(lines) + "\n"


def build_source(state: str | None = None, render: bool = True,
                 expected: int = ANY_LENGTH) -> str:
    """Return solver + tables as one source.

    Args:
        state: when given, the built-in test table is replaced by this single
            state (used for per-state measurements and tests).
        render: False drops every RENDER_BEGIN..RENDER_END block, giving the
            build Ripes' CLI can assemble (it has no LED peripheral).
        expected: expected solution length for ``state`` (255 = do not check).
    """
    solver = SOLVER.read_text(encoding="utf-8")
    if state is not None:
        entry = "tests:\n" + test_entry(state, expected)
        solver, count = TESTS_BLOCK.subn(lambda _: entry, solver, count=1)
        if count != 1:
            raise RuntimeError("TESTS_BEGIN/TESTS_END block not found in src/solver.s")
    source = solver.rstrip("\n") + "\n\n" + TABLES.read_text(encoding="utf-8")
    return source if render else RENDER_BLOCK.sub("", source)


def main(argv: list[str]) -> int:
    """Write the combined file."""
    render = "--no-render" not in argv
    args = [a for a in argv[1:] if a != "--no-render"]
    state = args[0] if args else None
    default = DEFAULT_OUT if render else DEFAULT_OUT.with_name("rubik_cli.s")
    out = Path(args[1]) if len(args) > 1 else default
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_source(state, render), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
