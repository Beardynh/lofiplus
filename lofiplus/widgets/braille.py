"""
BrailleCanvas — sub-cell terminal drawing surface.

Braille patterns (U+2800–U+28FF) pack a 2×4 dot grid into one terminal
cell, giving 2× horizontal and 4× vertical resolution. This is the same
technique btop/gtop use for their smooth graphs.

Dot bit layout per cell (Unicode standard):

        col 0   col 1
  row0  0x01    0x08
  row1  0x02    0x10
  row2  0x04    0x20
  row3  0x40    0x80

Memory discipline: bit buffer (bytearray) and per-cell color list are
allocated once per resize and reused every frame — zero per-frame
allocation beyond the rendered Text.
"""

from __future__ import annotations

from rich.text import Text

# DOTS[row][col] → bit
DOTS = (
    (0x01, 0x08),
    (0x02, 0x10),
    (0x04, 0x20),
    (0x40, 0x80),
)

# Pre-computed: mask of column `col` dots covering rows [a, b) within a cell
# _COL_SPAN[col][a][b] for 0 <= a <= b <= 4
_COL_SPAN: list[list[list[int]]] = [
    [[0] * 5 for _ in range(5)] for _ in range(2)
]
for _col in range(2):
    for _a in range(5):
        for _b in range(_a, 5):
            m = 0
            for _r in range(_a, _b):
                m |= DOTS[_r][_col]
            _COL_SPAN[_col][_a][_b] = m

BRAILLE_BASE = 0x2800


class BrailleCanvas:
    """Fixed-size dot canvas with one color per terminal cell."""

    def __init__(self) -> None:
        self._w = 0           # cells
        self._h = 0           # cells
        self._bits: bytearray = bytearray()
        self._colors: list[str | None] = []

    @property
    def width_px(self) -> int:
        return self._w * 2

    @property
    def height_px(self) -> int:
        return self._h * 4

    def resize(self, w_cells: int, h_cells: int) -> None:
        """(Re)allocate buffers only when dimensions change."""
        if w_cells == self._w and h_cells == self._h:
            return
        self._w = max(0, w_cells)
        self._h = max(0, h_cells)
        n = self._w * self._h
        self._bits   = bytearray(n)
        self._colors = [None] * n

    def clear(self) -> None:
        """Zero the canvas in place (no reallocation)."""
        for i in range(len(self._bits)):
            self._bits[i] = 0
        for i in range(len(self._colors)):
            self._colors[i] = None

    def set(self, px: int, py: int) -> None:
        """Set a single dot (pixel coords). Out-of-bounds is a no-op."""
        if 0 <= px < self._w * 2 and 0 <= py < self._h * 4:
            self._bits[(py // 4) * self._w + (px // 2)] |= DOTS[py % 4][px % 2]

    def vline(self, px: int, y0: int, y1: int) -> None:
        """Fill dots in pixel column px for rows [y0, y1] inclusive.

        Works cell-wise (≤1 OR per crossed cell) instead of per-pixel,
        which keeps full-height fills cheap at 30 FPS.
        """
        if px < 0 or px >= self._w * 2 or y1 < y0:
            return
        y0 = max(0, y0)
        y1 = min(self._h * 4 - 1, y1)
        if y1 < y0:
            return
        col   = px % 2
        cellx = px // 2
        cy0, cy1 = y0 // 4, y1 // 4
        for cy in range(cy0, cy1 + 1):
            a = y0 - cy * 4 if cy == cy0 else 0
            b = (y1 - cy * 4 + 1) if cy == cy1 else 4
            self._bits[cy * self._w + cellx] |= _COL_SPAN[col][a][b]

    def set_cell_color(self, cx: int, cy: int, color: str) -> None:
        if 0 <= cx < self._w and 0 <= cy < self._h:
            self._colors[cy * self._w + cx] = color

    def cell_filled(self, cx: int, cy: int) -> bool:
        if 0 <= cx < self._w and 0 <= cy < self._h:
            return self._bits[cy * self._w + cx] != 0
        return False

    def render(self, default_color: str = "#cdd9e5") -> Text:
        """Render to a Rich Text, run-length grouping spans by color."""
        out = Text(no_wrap=True)
        w, h = self._w, self._h
        bits, colors = self._bits, self._colors
        for cy in range(h):
            row_off = cy * w
            run_chars: list[str] = []
            run_color: str | None = ""
            for cx in range(w):
                b = bits[row_off + cx]
                if b == 0:
                    ch, color = " ", None
                else:
                    ch    = chr(BRAILLE_BASE + b)
                    color = colors[row_off + cx] or default_color
                if color != run_color and run_chars:
                    out.append("".join(run_chars),
                               style=run_color if run_color else "")
                    run_chars = []
                run_color = color
                run_chars.append(ch)
            if run_chars:
                out.append("".join(run_chars), style=run_color if run_color else "")
            if cy < h - 1:
                out.append("\n")
        return out
