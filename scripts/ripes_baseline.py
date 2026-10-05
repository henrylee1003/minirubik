# Usage: python scripts/ripes_baseline.py rate | memory
# Description: Stage 1 baseline measurements of the Ripes simulator itself,
#              taken with a tight store loop (no solver involved):
#              rate   - retired instructions/second per processor model
#                       (7 runs on an idle machine; fastest run and range)
#              memory - host bytes per guest byte (peak working set of Ripes
#                       against the number of guest bytes stored)
# Input: none
# Output: tables on stdout; results/ripes_rate.csv, results/ripes_memory.csv
# Dependencies: psutil (pip install psutil); Ripes with RV32_ISS (set RIPES env var).
#               Windows only: it reads the peak working set of Ripes.exe.
"""Stage 1: how fast Ripes retires instructions and what guest memory costs the host."""

from __future__ import annotations

import csv
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
RIPES = Path(os.environ.get("RIPES", r"C:\Users\User\Downloads\Ripes\Ripes.exe"))
RESULTS = ROOT / "results"
RATE_RUNS = 7

# Tight store loop: 4 retired instructions per stored word, 4 guest bytes each.
STORE_LOOP = """\
.text
    li   t0, 0x20000000
    li   t1, {words}
loop:
    sw   t1, 0(t0)
    addi t0, t0, 4
    addi t1, t1, -1
    bnez t1, loop
    li   a7, 10
    ecall
"""


@dataclass
class Run:
    """Result of one Ripes CLI run."""

    iret: int
    cycles: int
    model_ms: int
    peak_bytes: int


def run_ripes(source: str, proc: str) -> Run:
    """Assemble and run ``source`` in Ripes CLI mode; collect telemetry."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "prog.s"
        src.write_text(source, encoding="utf-8")
        cmd = [str(RIPES), "--mode", "cli", "--src", str(src), "-t", "asm", "--proc", proc,
               "--iret", "--cycles", "--exectime"]
        child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        peak = 0
        try:
            ps = psutil.Process(child.pid)
            while child.poll() is None:  # the OS keeps the peak; read it until exit
                try:
                    peak = max(peak, ps.memory_info().peak_wset)
                except psutil.Error:
                    break
                time.sleep(0.02)
        except psutil.Error:
            pass
        text = child.communicate()[0]
    if "ERROR" in text:
        raise RuntimeError(text)

    def field(name: str) -> int:
        m = re.search(rf"===== {name}\n(\d+)", text)
        if not m:
            raise RuntimeError(f"missing '{name}' in Ripes report:\n{text}")
        return int(m.group(1))

    return Run(field("instructions retired"), field("cycles"),
               field(r"wall-clock model execution time \(ms\)"), peak)


def cmd_rate() -> None:
    """Retired instructions per second for each processor model.

    The retired-instruction and cycle counts are exact and identical on every
    run; only the wall-clock time moves with host load. Like report.md, this
    reports the fastest of several runs on an idle machine, plus the range.
    """
    plan = [("RV32_ISS", 4_000_000), ("RV32_SS", 150_000), ("RV32_5S", 40_000),
            ("RV32_6S_DUAL", 15_000)]
    print(f"{'processor':<14}{'iret':>12}{'cycles':>12}{'model ms min..max':>20}"
          f"{'instr/s (fastest)':>20}")
    rows = []
    for proc, words in plan:
        runs = [run_ripes(STORE_LOOP.format(words=words), proc) for _ in range(RATE_RUNS)]
        if len({(r.iret, r.cycles) for r in runs}) != 1:
            raise RuntimeError(f"{proc}: instruction or cycle count changed between runs")
        ms = sorted(r.model_ms for r in runs)
        iret, cycles = runs[0].iret, runs[0].cycles
        fastest, slowest = iret * 1000 / ms[0], iret * 1000 / ms[-1]
        rows.append([proc, iret, cycles, RATE_RUNS, ms[0], ms[-1], round(fastest), round(slowest)])
        print(f"{proc:<14}{iret:>12,}{cycles:>12,}{f'{ms[0]}..{ms[-1]}':>20}{fastest:>20,.0f}")
    write_csv("ripes_rate.csv", ["processor", "iret", "cycles", "runs", "fastest_ms",
                                 "slowest_ms", "instr_per_s_fastest", "instr_per_s_slowest"],
              rows)


def cmd_memory() -> None:
    """Host peak working set against guest bytes stored; first size is the control."""
    print(f"{'processor':<10}{'guest bytes':>14}{'host peak bytes':>18}{'delta/guest byte':>18}")
    rows = []
    for proc, sizes in (("RV32_ISS", [1024, 262_144, 524_288, 1_048_576, 2_097_152]),
                        ("RV32_SS", [1024, 65_536, 131_072])):
        base = None
        for words in sizes:
            peak = statistics.median(
                run_ripes(STORE_LOOP.format(words=words), proc).peak_bytes for _ in range(3))
            guest = words * 4
            if base is None:
                base = (guest, peak)
                ratio = float("nan")
            else:
                ratio = (peak - base[1]) / (guest - base[0])
            rows.append([proc, guest, int(peak), round(ratio, 2)])
            print(f"{proc:<10}{guest:>14,}{int(peak):>18,}{ratio:>18.1f}")
    write_csv("ripes_memory.csv", ["processor", "guest_bytes", "host_peak_bytes",
                                   "host_bytes_per_guest_byte"], rows)


def write_csv(name: str, header: list[str], rows: list[list[object]]) -> None:
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / name).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"wrote {RESULTS / name}")


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if len(argv) != 2 or argv[1] not in ("rate", "memory"):
        print("usage: python scripts/ripes_baseline.py rate | memory", file=sys.stderr)
        return 2
    if argv[1] == "rate":
        cmd_rate()
    else:
        cmd_memory()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
