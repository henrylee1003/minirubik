# Usage: python scripts/ripes_measure.py vectors | depth11 [--workers N]
# Description: Measure the RV32I solver with the Ripes CLI, renderer compiled out:
#              vectors - run tests/solutions.txt on RV32_ISS and RV32_5S and
#                        compare each output with the expected one
#              depth11 - retired instructions on RV32_ISS for every
#                        distance-11 state (the pass condition)
#              The Ripes baseline itself is measured by scripts/ripes_baseline.py.
# Input: tests/solutions.txt (state|solution per line) for "vectors"; none for "depth11"
# Output: tables on stdout; results/ripes_vectors.csv, results/ripes_depth11_iret.csv
# Dependencies: Ripes with RV32_ISS (set RIPES env var); standard library only
"""Stage 4: retired instructions of the assembly solver on the real Ripes."""

from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from build_ripes import build_source  # noqa: E402
from rubik_ref import (  # noqa: E402
    NUM_PERMS,
    NUM_TWISTS,
    build_move_tables,
    unrank_perm,
    unrank_twist,
)

RIPES = Path(os.environ.get("RIPES", r"C:\Users\User\Downloads\Ripes\Ripes.exe"))
RESULTS = ROOT / "results"
VECTORS = ROOT / "tests" / "solutions.txt"
INSTR_LIMIT = 50_000_000
DIAMETER = 11


@dataclass
class Run:
    """Result of one Ripes CLI run."""

    output: str
    iret: int
    cycles: int
    wall_s: float


def run_ripes(source: str, proc: str = "RV32_ISS") -> Run:
    """Assemble and run ``source`` in Ripes CLI mode."""
    with tempfile.TemporaryDirectory() as tmp:  # ASCII path; Ripes dislikes others
        src = Path(tmp) / "prog.s"
        src.write_text(source, encoding="utf-8")
        cmd = [str(RIPES), "--mode", "cli", "--src", str(src), "-t", "asm", "--proc", proc,
               "--iret", "--cycles"]
        start = time.perf_counter()
        text = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, check=False).stdout
        wall = time.perf_counter() - start
    if "ERROR" in text:
        raise RuntimeError(text)

    def field(name: str) -> int:
        m = re.search(rf"===== {name}\n(\d+)", text)
        if not m:
            raise RuntimeError(f"missing '{name}' in Ripes report:\n{text}")
        return int(m.group(1))

    output = text.split("\nProgram exited", 1)[0].split("=====", 1)[0]
    return Run(output.strip("\n"), field("instructions retired"), field("cycles"), wall)


def load_vectors() -> list[tuple[str, str]]:
    """Read ``state|solution`` lines, skipping comments."""
    pairs = []
    for line in VECTORS.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            state, solution = line.split("|")
            pairs.append((state, solution))
    return pairs


def cmd_vectors() -> None:
    """Every test vector on RV32_ISS and RV32_5S; outputs must match."""
    print(f"{'state':<16}{'processor':<10}{'iret':>12}{'cycles':>12}{'s':>8}  ok  output")
    rows = []
    for state, expected in load_vectors():
        for proc in ("RV32_ISS", "RV32_5S"):
            r = run_ripes(build_source(state, render=False), proc)
            ok = r.output == expected
            rows.append([state, proc, r.iret, r.cycles, round(r.wall_s, 1), ok, r.output])
            print(f"{state:<16}{proc:<10}{r.iret:>12,}{r.cycles:>12,}{r.wall_s:>8.1f}  "
                  f"{'ok' if ok else 'FAIL'}  {r.output}", flush=True)
    _write_csv("ripes_vectors.csv", ["state", "processor", "iret", "cycles", "wall_s", "match",
                                     "output"], rows)


def depth11_inputs() -> list[str]:
    """BFS over all 3,674,160 states; return those at distance 11 as input text.

    This runs on the PC only. The set is closed under inversion, so it does
    not matter that the solver searches from the inverse of its input.
    """
    perm_mv, twist_mv = build_move_tables()
    seen = bytearray(NUM_PERMS * NUM_TWISTS)
    seen[0] = 1
    frontier, last, depth = [0], [0], 0
    while frontier:
        nxt = []
        for s in frontier:
            p, t = divmod(s, NUM_TWISTS)
            for f in range(3):
                q, u = p, t
                for _ in range(3):
                    q, u = perm_mv[f][q], twist_mv[f][u]
                    k = q * NUM_TWISTS + u
                    if not seen[k]:
                        seen[k] = 1
                        nxt.append(k)
        if nxt:
            last, depth = nxt, depth + 1
        frontier = nxt
    if depth != DIAMETER:
        raise RuntimeError(f"unexpected diameter {depth}")
    inputs = []
    for s in last:
        p, t = divmod(s, NUM_TWISTS)
        digits = unrank_perm(p) + unrank_twist(t)
        inputs.append("".join(str(v + 1) for v in digits))
    return inputs


def cmd_depth11(workers: int) -> None:
    """--iret on RV32_ISS for every distance-11 input."""
    start = time.perf_counter()
    inputs = depth11_inputs()
    print(f"{len(inputs)} distance-11 states found in {time.perf_counter() - start:.0f} s")

    def one(state: str) -> list[object]:
        r = run_ripes(build_source(state, render=False))
        return [state, r.iret, len(r.output.split())]

    start = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(one, inputs))
    rows.sort(key=lambda r: (-int(r[1]), str(r[0])))  # type: ignore[call-overload]
    _write_csv("ripes_depth11_iret.csv", ["input", "iret", "moves"], rows)
    irets = sorted(int(r[1]) for r in rows)  # type: ignore[call-overload]
    print(f"{len(rows)} inputs in {time.perf_counter() - start:.0f} s; first 5 rows:")
    for r in rows[:5]:
        print("  " + ",".join(str(v) for v in r))
    print(f"iret: min {irets[0]:,}  median {irets[len(irets) // 2]:,}  max {irets[-1]:,}")
    print(f"all {DIAMETER} moves: {all(r[2] == DIAMETER for r in rows)}")
    over = sum(i > INSTR_LIMIT for i in irets)
    print(f"over {INSTR_LIMIT:,}: {over}  ->  {'PASS' if over == 0 else 'FAIL'}")


def _write_csv(name: str, header: list[str], rows: list[list[object]]) -> None:
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / name).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"wrote {RESULTS / name}")


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if len(argv) < 2 or argv[1] not in ("vectors", "depth11"):
        print(__doc__, file=sys.stderr)
        return 2
    if argv[1] == "vectors":
        cmd_vectors()
    else:
        workers = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 4
        cmd_depth11(workers)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
