# Usage: python src/rubik_ref.py <14-digit state>   e.g. python src/rubik_ref.py 21345671111111
# Description: Reference 2x2x2 solver that mirrors the planned RV32I design:
#              small move tables + runtime-built pruning tables + iterative IDA*.
#              Prints the same optimal solution as sysprog21/minirubik.
# Input: 14 digits = 7 permutation digits (1-7, each once) + 7 twist digits (1-3)
# Output: one line of moves (e.g. "B' R' D2 ..."); search node count on stderr
# Dependencies: none (standard library only)
"""Reference model for the RV32I minirubik solver.

Design (each part maps 1:1 to the planned assembly):

* Coordinates: permutation rank (0..5039) and twist rank (0..728).
* Move tables: only the three quarter turns R, B, D are stored.
  Half and inverse turns are made by applying the quarter turn again.
* Pruning tables: built at runtime by BFS over each coordinate alone.
  They give a lower bound of the distance, not the full distance table.
* Search: IDA* with an explicit stack (no recursion). The search starts
  from the inverse of the input and tries moves in the original BFS order,
  so the first hit is the lexicographically smallest shortest path. Its
  reversed inverse equals the original program's output exactly.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

NUM_CORNERS = 7
NUM_PERMS = 5040  # 7!
NUM_TWISTS = 729  # 3^6
NUM_FACES = 3
FACE_NAMES = "RBD"
SUFFIXES = ("", "2", "'")
UNSEEN = 0xFF
MAX_DEPTH = 11

# Same quarter-turn definition as minirubik/mini.c:
# first 7 chars = source position, last 7 chars = twist added.
TURN_MAP = ("14203561202100", "01245630001212", "02531460000000")

State = tuple[tuple[int, ...], tuple[int, ...]]
SOLVED: State = (tuple(range(NUM_CORNERS)), (0,) * NUM_CORNERS)


def quarter_turn(state: State, face: int) -> State:
    """Apply one clockwise quarter turn of ``face`` to a cubie-level state."""
    perm, twist = state
    spec = TURN_MAP[face]
    src = [int(c) for c in spec[:NUM_CORNERS]]
    add = [int(c) for c in spec[NUM_CORNERS:]]
    return (
        tuple(perm[src[i]] for i in range(NUM_CORNERS)),
        tuple((twist[src[i]] + add[i]) % 3 for i in range(NUM_CORNERS)),
    )


def rank_perm(perm: tuple[int, ...]) -> int:
    """Lehmer rank of a 7-permutation (0..5039)."""
    rank = 0
    for i in range(NUM_CORNERS):
        smaller = sum(perm[j] < perm[i] for j in range(i + 1, NUM_CORNERS))
        rank = rank * (NUM_CORNERS - i) + smaller  # asm: shift-add multiply
    return rank


def unrank_perm(rank: int) -> tuple[int, ...]:
    """Inverse of :func:`rank_perm`."""
    digits = []
    for base in range(1, NUM_CORNERS + 1):
        digits.append(rank % base)
        rank //= base
    digits.reverse()
    pool = list(range(NUM_CORNERS))
    return tuple(pool.pop(d) for d in digits)


def rank_twist(twist: tuple[int, ...]) -> int:
    """Base-3 rank of the first six twists (the 7th is implied)."""
    rank = 0
    for i in range(NUM_CORNERS - 1):
        rank = rank * 3 + twist[i]  # asm: (x << 1) + x
    return rank


def unrank_twist(rank: int) -> tuple[int, ...]:
    """Inverse of :func:`rank_twist`; the 7th twist makes the sum 0 mod 3."""
    twist = [0] * NUM_CORNERS
    for i in range(NUM_CORNERS - 2, -1, -1):
        twist[i] = rank % 3
        rank //= 3
    twist[-1] = -sum(twist[:-1]) % 3
    return tuple(twist)


def build_move_tables() -> tuple[list[list[int]], list[list[int]]]:
    """Build quarter-turn tables ``perm_mv[face][rank]`` and ``twist_mv[face][rank]``."""
    identity_twist = (0,) * NUM_CORNERS
    identity_perm = tuple(range(NUM_CORNERS))
    perm_mv = [
        [rank_perm(quarter_turn((unrank_perm(r), identity_twist), f)[0]) for r in range(NUM_PERMS)]
        for f in range(NUM_FACES)
    ]
    twist_mv = [
        [rank_twist(quarter_turn((identity_perm, unrank_twist(r)), f)[1]) for r in range(NUM_TWISTS)]
        for f in range(NUM_FACES)
    ]
    return perm_mv, twist_mv


def build_prune_table(move: list[list[int]], size: int) -> bytearray:
    """BFS from solved over one coordinate; same loop shape as the asm version."""
    dist = bytearray([UNSEEN]) * size
    queue = [0] * size  # fixed-size static queue, no heap in asm
    dist[0] = 0
    head, tail = 0, 1
    while head < tail:
        cur = queue[head]
        head += 1
        for face in range(NUM_FACES):
            nxt = cur
            for _ in range(3):  # quarter, half, inverse
                nxt = move[face][nxt]
                if dist[nxt] == UNSEEN:
                    dist[nxt] = dist[cur] + 1
                    queue[tail] = nxt
                    tail += 1
    return dist


def parse_state(text: str) -> State:
    """Parse and validate the 14-digit input, like the original solver."""
    if len(text) != 2 * NUM_CORNERS or not text.isdigit():
        raise ValueError("state must be 14 digits")
    perm = tuple(int(c) - 1 for c in text[:NUM_CORNERS])
    twist = tuple(int(c) - 1 for c in text[NUM_CORNERS:])
    if sorted(perm) != list(range(NUM_CORNERS)):
        raise ValueError("permutation digits must be 1-7, each exactly once")
    if any(t not in (0, 1, 2) for t in twist):
        raise ValueError("twist digits must be 1-3")
    if sum(twist) % 3:
        raise ValueError("twist sum must be divisible by 3")
    return perm, twist


def invert(state: State) -> State:
    """Group inverse: ``invert(x)`` followed by the moves of ``x`` gives solved."""
    perm, twist = state
    inv = [0] * NUM_CORNERS
    for i, p in enumerate(perm):
        inv[p] = i
    return tuple(inv), tuple(-twist[inv[i]] % 3 for i in range(NUM_CORNERS))


@dataclass
class Frame:
    """One explicit DFS stack frame (fixed size, 12 frames max in asm)."""

    perm: int
    twist: int
    last_face: int
    face: int = 0
    turns: int = 0  # quarter turns already applied for ``face`` (0..3)
    cur_perm: int = 0
    cur_twist: int = 0


@dataclass
class Solver:
    """Holds the move and pruning tables (static data in the asm version)."""

    perm_mv: list[list[int]]
    twist_mv: list[list[int]]
    perm_prune: bytearray
    twist_prune: bytearray

    @classmethod
    def create(cls) -> Solver:
        """Build all tables the same way the asm program will."""
        perm_mv, twist_mv = build_move_tables()
        return cls(
            perm_mv,
            twist_mv,
            build_prune_table(perm_mv, NUM_PERMS),
            build_prune_table(twist_mv, NUM_TWISTS),
        )

    def heuristic(self, perm: int, twist: int) -> int:
        """Admissible lower bound: max of the two pruning tables."""
        return max(self.perm_prune[perm], self.twist_prune[twist])

    def search(self, perm: int, twist: int) -> tuple[list[int], int]:
        """IDA* from (perm, twist) to solved.

        Returns:
            The lexicographically smallest shortest move list (move = face*3 + n,
            meaning n+1 quarter turns) and the number of expanded nodes.
        """
        nodes = 0
        bound = self.heuristic(perm, twist)
        while bound <= MAX_DEPTH:
            stack = [Frame(perm, twist, last_face=-1)]
            path: list[int] = []
            while stack:
                top = stack[-1]
                depth = len(stack) - 1
                if depth == bound and top.perm == 0 and top.twist == 0:
                    return path, nodes
                if top.face == NUM_FACES or depth == bound:
                    stack.pop()
                    if path:
                        path.pop()
                    continue
                if top.face == top.last_face or top.turns == 3:
                    top.face += 1
                    top.turns = 0
                    continue
                if top.turns == 0:
                    top.cur_perm, top.cur_twist = top.perm, top.twist
                # Cumulative quarter turns: one table lookup per child.
                top.cur_perm = self.perm_mv[top.face][top.cur_perm]
                top.cur_twist = self.twist_mv[top.face][top.cur_twist]
                move = top.face * 3 + top.turns
                top.turns += 1
                nodes += 1
                if depth + 1 + self.heuristic(top.cur_perm, top.cur_twist) > bound:
                    continue
                path.append(move)
                stack.append(Frame(top.cur_perm, top.cur_twist, last_face=top.face))
            bound += 1
        raise RuntimeError("no solution within 11 moves")

    def solve(self, state: State) -> tuple[list[int], int]:
        """Return the original program's optimal solution and the node count."""
        inv_perm, inv_twist = invert(state)
        path, nodes = self.search(rank_perm(inv_perm), rank_twist(inv_twist))
        # Reverse the path and invert each move: n -> 2 - n.
        return [(m // 3) * 3 + (2 - m % 3) for m in reversed(path)], nodes


def format_moves(moves: list[int]) -> str:
    """Format move codes as text, e.g. [2, 3] -> "R' B"."""
    return " ".join(FACE_NAMES[m // 3] + SUFFIXES[m % 3] for m in moves)


def apply_moves(state: State, moves: list[int]) -> State:
    """Apply move codes to a cubie-level state (used to check solutions)."""
    for m in moves:
        for _ in range(m % 3 + 1):
            state = quarter_turn(state, m // 3)
    return state


def main(argv: list[str]) -> int:
    """CLI entry point."""
    if len(argv) != 2:
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    try:
        state = parse_state(argv[1])
    except ValueError as err:
        print(f"invalid state: {err}", file=sys.stderr)
        return 2
    moves, nodes = Solver.create().solve(state)
    print(format_moves(moves))
    print(f"nodes: {nodes}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
