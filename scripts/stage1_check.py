# Usage: python scripts/stage1_check.py
# Description: Recompute, from first principles, every number the write-up
#              quotes from report.md or the assignment text (no measurement).
# Input: none
# Output: one line per number: recomputed value, quoted value, OK/DIFF
# Dependencies: none (standard library only)
"""Arithmetic cross-check of quoted figures."""

from __future__ import annotations

from math import factorial

KIB, MIB = 1024, 1024 * 1024


def check(name: str, got: object, quoted: object) -> None:
    print(f"{'OK  ' if got == quoted else 'DIFF'} {name:<52} {got}   (quoted {quoted})")


def main() -> None:
    states = factorial(7) * 3**6
    check("states = 7! * 3^6", states, 3_674_160)
    check("all twist fillings 3^7", 3**7, 2_187)
    check("R twist deltas sum", sum(int(c) for c in "1202100"), 6)
    check("B twist deltas sum", sum(int(c) for c in "0001212"), 6)
    table, queue = states, states * 4
    trans = 3 * (factorial(7) + 3**6) * 2
    peak = table + queue + trans
    check("move-per-state table bytes", table, 3_674_160)
    check("queue bytes (uint32 per state)", queue, 14_696_640)
    check("transition tables bytes", trans, 34_614)
    check("peak bytes", peak, 18_405_414)
    check("peak MiB", round(peak / MIB, 3), 17.553)
    check("queue share %", round(100 * queue / peak, 1), 79.8)
    check("table share %", round(100 * table / peak, 1), 20.0)
    check("transition share %", round(100 * trans / peak, 1), 0.2)
    edges = states * 9
    check("edges = states * 9", edges, 33_067_440)
    check("transition updates = edges * 2", edges * 2, 66_134_880)
    check("instructions at 15 per update (about 1e9)", edges * 2 * 15, 992_023_200)
    budget = 128 * KIB
    check("budget bytes", budget, 131_072)
    check("table / budget (x)", round(table / budget), 28)
    packed = states // 2
    check("4-bit packed table KiB", round(packed / KIB), 1_794)
    check("packed / budget (x)", round(packed / budget), 14)
    check("budget left after transition tables", budget - trans, 96_458)
    check("sec. 7 nibble-sweep peak MiB", round((table + trans) / MIB, 3), 3.537)
    tree = 1 + sum(9 * 6 ** (d - 1) for d in range(1, 12))
    check("depth-11 search tree nodes (9 then 6 moves)", tree, 653_034_700)
    dist = [1, 9, 54, 321, 1847, 9992, 50136, 227536, 870072, 1887748, 623800, 2644]
    check("distance distribution sums to states", sum(dist), states)
    check("share at distance 9 %", round(100 * dist[9] / states, 1), 51.4)
    check("share at distance 8..10 %", round(100 * sum(dist[8:11]) / states, 1), 92.0)
    check("share at distance 11 %", round(100 * dist[11] / states, 3), 0.072)
    check("draws per distance-11 hit", round(states / dist[11]), 1_390)
    check("nodes for 5e7 at 200 instr/node", 50_000_000 // 200, 250_000)


if __name__ == "__main__":
    main()
