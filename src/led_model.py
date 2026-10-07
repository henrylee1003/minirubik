# Usage: python src/led_model.py <14-digit state>   e.g. python src/led_model.py 21345671111111
# Description: LED 35x25 unfolded-cube model. Maps (cubie, twist) to sticker
#              pixels/colors for the RV32I program, and renders preview PNGs.
# Input: 14-digit state (same format as src/rubik_ref.py)
# Output: build/led_frames.png (scramble -> each move -> solved)
# Dependencies: none (standard library only)
"""LED matrix model for the 2x2x2 solver.

Geometry: x = right, y = up, z = front. Corner positions follow the original
README (0 = front-upper-left ... 7 = back-upper-left). Each position has three
facelets ordered: U/D sticker first, then counter-clockwise seen from outside.
A cubie with twist ``o`` shows its home facelet ``(j - o) mod 3`` on facelet
``j``. This convention is checked against TURN_MAP by an independent 3D
sticker simulation (see tests/test_led_model.py).

Net layout on the 35x25 matrix, as the assignment specifies: each facelet is
4 LEDs wide and 3 tall, facelets of one face touch, and one dark column/row
separates faces. 8 * 4 + 3 = 35 columns, 6 * 3 + 2 = 20 rows (rows 2..21)::

        U
     L  F  R  B
        D
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

from rubik_ref import SOLVED, State, Solver, parse_state, quarter_turn

WIDTH = 35
HEIGHT = 25
STICKER_W = 4
STICKER_H = 3
FACE_STEP_X = 2 * STICKER_W + 1  # two facelets + one separator column
FACE_STEP_Y = 2 * STICKER_H + 1  # two facelets + one separator row
ORIGIN_X = 0
ORIGIN_Y = 2  # 5 spare rows: 2 above, 3 below

Vec = tuple[int, int, int]
POSITIONS: list[Vec] = [
    (-1, 1, 1), (1, 1, 1), (1, -1, 1), (-1, -1, 1),
    (1, 1, -1), (1, -1, -1), (-1, -1, -1), (-1, 1, -1),
]
# Face -> (net column, net row, RGB). Standard color scheme.
FACES: dict[Vec, tuple[int, int, int]] = {
    (0, 1, 0): (1, 0, 0xFFFFFF),   # U white
    (-1, 0, 0): (0, 1, 0xFF5800),  # L orange
    (0, 0, 1): (1, 1, 0x009B48),   # F green
    (1, 0, 0): (2, 1, 0xB71234),   # R red
    (0, 0, -1): (3, 1, 0x0046AD),  # B blue
    (0, -1, 0): (1, 2, 0xFFD500),  # D yellow
}
# Quarter-turn faces used by TURN_MAP: (axis, layer sign) for R, B, D.
TURN_AXES = ((0, 1), (2, -1), (1, -1))


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec, b: Vec) -> int:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def facelets(pos: Vec) -> list[Vec]:
    """Outward normals of a corner: U/D first, then counter-clockwise from outside."""
    x, y, z = pos
    ny, nx, nz = (0, y, 0), (x, 0, 0), (0, 0, z)
    a, b = (nx, nz) if _dot(_cross(ny, nx), pos) > 0 else (nz, nx)
    return [ny, a, b]


def sticker_xy(pos: Vec, normal: Vec) -> tuple[int, int]:
    """Top-left LED (x, y) of the sticker on ``normal`` at corner ``pos``."""
    x, y, z = pos
    col, row, _ = FACES[normal]
    lookup = {
        (0, 0, 1): ((x + 1) // 2, (1 - y) // 2),
        (0, 1, 0): ((x + 1) // 2, (z + 1) // 2),
        (0, -1, 0): ((x + 1) // 2, (1 - z) // 2),
        (-1, 0, 0): ((z + 1) // 2, (1 - y) // 2),
        (1, 0, 0): ((1 - z) // 2, (1 - y) // 2),
        (0, 0, -1): ((1 - x) // 2, (1 - y) // 2),
    }
    sc, sr = lookup[normal]
    return (ORIGIN_X + col * FACE_STEP_X + sc * STICKER_W,
            ORIGIN_Y + row * FACE_STEP_Y + sr * STICKER_H)


def led_offsets() -> list[int]:
    """Byte offset of each (position*3 + facelet) sticker's top-left LED."""
    out = []
    for pos in POSITIONS:
        for n in facelets(pos):
            x, y = sticker_xy(pos, n)
            out.append((y * WIDTH + x) * 4)
    return out


def cubie_colors() -> list[int]:
    """RGB of each (cubie*3 + home facelet)."""
    return [FACES[n][2] for pos in POSITIONS for n in facelets(pos)]


def frame(state: State) -> list[int]:
    """Render a cubie-level state to WIDTH*HEIGHT RGB values (0 = off)."""
    perm, twist = state
    pixels = [0] * (WIDTH * HEIGHT)
    offs, cols = led_offsets(), cubie_colors()
    for pos in range(8):
        cubie, o = (0, 0) if pos == 0 else (perm[pos - 1] + 1, twist[pos - 1])
        for j in range(3):
            color = cols[cubie * 3 + (j - o) % 3]
            base = offs[pos * 3 + j] // 4
            for dy in range(STICKER_H):
                for dx in range(STICKER_W):
                    pixels[base + dy * WIDTH + dx] = color
    return pixels


def animation_frames(state: State, moves: list[int]) -> list[list[int]]:
    """Frames the RV32I program draws: scramble, then after each move."""
    frames = [frame(state)]
    for m in moves:
        for _ in range(m % 3 + 1):
            state = quarter_turn(state, m // 3)
        frames.append(frame(state))
    return frames


# ---- independent 3D sticker simulation (used only to verify the tables) ----
def rotate(v: Vec, face: int) -> Vec:
    """Rotate ``v`` 90 degrees clockwise as seen from outside ``face`` (R/B/D)."""
    axis, k = TURN_AXES[face]
    x, y, z = v
    if axis == 0:
        return (x, z * k, -y * k)
    if axis == 1:
        return (-z * k, y, x * k)
    return (y * k, -x * k, z)


def sticker_turn(stickers: dict[tuple[Vec, Vec], int], face: int) -> dict[tuple[Vec, Vec], int]:
    """Apply one quarter turn to a {(position, normal): color} sticker map."""
    axis, sign = TURN_AXES[face]
    return {
        ((rotate(p, face), rotate(n, face)) if p[axis] == sign else (p, n)): c
        for (p, n), c in stickers.items()
    }


def solved_stickers() -> dict[tuple[Vec, Vec], int]:
    return {(p, n): FACES[n][2] for p in POSITIONS for n in facelets(p)}


def stickers_to_frame(stickers: dict[tuple[Vec, Vec], int]) -> list[int]:
    pixels = [0] * (WIDTH * HEIGHT)
    for (p, n), color in stickers.items():
        x, y = sticker_xy(p, n)
        for dy in range(STICKER_H):
            for dx in range(STICKER_W):
                pixels[(y + dy) * WIDTH + x + dx] = color
    return pixels


# ---- PNG preview (stdlib only) ----
def write_png(frames: list[list[int]], path: Path, scale: int = 8) -> None:
    """Write frames side by side as one PNG, each LED a ``scale``-px square."""
    gap = 2 * scale
    w = len(frames) * WIDTH * scale + (len(frames) - 1) * gap
    h = HEIGHT * scale
    rows = []
    for py in range(h):
        row = bytearray([0])
        y = py // scale
        for i, fr in enumerate(frames):
            for px in range(WIDTH * scale):
                c = fr[y * WIDTH + px // scale]
                edge = px % scale == scale - 1 or py % scale == scale - 1
                c = 0x202020 if edge else (c or 0x101010)
                row += bytes(((c >> 16) & 255, (c >> 8) & 255, c & 255))
            if i < len(frames) - 1:
                row += bytes(3 * gap)
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def main(argv: list[str]) -> int:
    """Render scramble -> solution frames to build/led_frames.png."""
    if len(argv) != 2:
        print("usage: python src/led_model.py <14-digit state>", file=sys.stderr)
        return 2
    state = parse_state(argv[1])
    moves, _ = Solver.create().solve(state)
    frames = animation_frames(state, moves)
    assert frames[-1] == frame(SOLVED)
    out = Path(__file__).resolve().parent.parent / "build" / "led_frames.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_png(frames, out)
    print(f"wrote {out} ({len(frames)} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
