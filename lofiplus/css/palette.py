"""Shared color palette — used by both .tcss and Python widget rendering."""

# GitHub Dark / Claude Code inspired
BG      = "#0d1117"
SURFACE = "#161b22"
BORDER  = "#21262d"
TEXT    = "#cdd9e5"
MUTED   = "#636e7b"
DIM     = "#2d333b"
ACCENT  = "#e6b450"
SUCCESS = "#57ab5a"
ERROR   = "#e5534b"
WARNING = "#fbbf24"

# Spectrum gradient (32 bands: bass → mid → treble)
SPECTRUM_COLORS = (
    ["#316dca"] * 5
    + ["#4a9be8"] * 3
    + ["#39c5cf"] * 6
    + ["#5ad4d0"] * 5
    + [ACCENT]    * 5
    + ["#d4922b"] * 4
    + [ERROR]     * 4
)
