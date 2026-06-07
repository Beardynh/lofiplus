
from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widget import Widget

from lofiplus.css.palette import BG

if TYPE_CHECKING:
    from lofiplus.core.spectrum_source import SpectrumSource

BANDS  = 32
FPS    = 30
N_GRAD = 24          # pre-computed gradient resolution per band


# ── Color helpers ───────────────────────────────────────────────────────

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"


def _lerp(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex(
        int(r1 + (r2 - r1) * t),
        int(g1 + (g2 - g1) * t),
        int(b1 + (b2 - b1) * t),
    )


# ── Base band colors ───────────────────────────────────────────────────

_BASE = (
    ["#9b8dd4"] * 6     # purple        — sub-bass / bass
    + ["#8b9eda"] * 3   # periwinkle
    + ["#39c5cf"] * 6   # cyan          — low mids
    + ["#5ad4d0"] * 4   # teal          — mids
    + ["#e6b450"] * 6   # amber         — high mids
    + ["#d4922b"] * 4   # dark amber    — presence
    + ["#e5534b"] * 3   # red           — treble peaks
)


# ── Pre-computed gradient look-up tables ───────────────────────────────
# _GRAD[band][level] → hex color   (level 0 = bottom, N_GRAD-1 = tip)
# _PEAK[band]        → hex color   (bright peak indicator)
# _REFL[band]        → hex color   (dim reflection)

_GRAD: list[list[str]] = []
_PEAK: list[str] = []
_REFL: list[str] = []

for _i in range(BANDS):
    _b = _BASE[_i]
    _dark = _lerp(_b, BG, 0.62)           # bottom: 62% toward background
    _mid  = _b                              # middle: base color
    _tip  = _lerp(_b, "#ffffff", 0.40)      # tip: 40% toward white (glow)
    _grad = []
    for _j in range(N_GRAD):
        t = _j / (N_GRAD - 1)
        if t < 0.55:
            # Bottom 55 %: dark → base
            _grad.append(_lerp(_dark, _mid, t / 0.55))
        elif t < 0.82:
            # Mid 27 %: base → bright
            _grad.append(_lerp(_mid, _lerp(_b, "#ffffff", 0.20), (t - 0.55) / 0.27))
        else:
            # Top 18 %: bright → glow
            _grad.append(_lerp(_lerp(_b, "#ffffff", 0.20), _tip, (t - 0.82) / 0.18))
    _GRAD.append(_grad)
    _PEAK.append(_lerp(_b, "#ffffff", 0.55))
    _REFL.append(_lerp(_b, BG, 0.78))


# ── Widget ─────────────────────────────────────────────────────────────

class SpectrumWidget(Widget):
    DEFAULT_CSS = f"""
    SpectrumWidget {{
        height: 14;
        min-height: 6;
        background: {BG};
        background-tint: {BG} 0%;
        padding: 0 1;
    }}
    """

    def __init__(self, source: "SpectrumSource", **kw) -> None:
        super().__init__(**kw)
        self._src    = source
        self._smooth = [0.0] * BANDS
        self._peaks  = [0.0] * BANDS
        self._p_vel  = [0.0] * BANDS
        self._busy   = False

    def on_mount(self) -> None:
        self.set_interval(1.0 / FPS, self._tick)

    def on_resize(self, event) -> None:
        self.refresh()

    # ── Animation tick ──────────────────────────────────────────────────

    def _tick(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            raw = self._src.get_bands()

            for i in range(BANDS):
                r = raw[i]
                s = self._smooth[i]
                # Frequency-dependent smoothing:
                #   bass = heavier (slower, weighty); treble = snappier
                if i < 8:
                    atk, rel = 0.65, 0.22
                elif i < 20:
                    atk, rel = 0.78, 0.30
                else:
                    atk, rel = 0.88, 0.40
                if r > s:
                    self._smooth[i] = s * (1 - atk) + r * atk
                else:
                    self._smooth[i] = s * (1 - rel) + r * rel

            # Peak hold with gravity
            for i in range(BANDS):
                v = self._smooth[i]
                if v >= self._peaks[i]:
                    self._peaks[i] = v
                    self._p_vel[i] = 0.0
                else:
                    self._p_vel[i] += 0.004
                    self._peaks[i] = max(0.0, self._peaks[i] - self._p_vel[i])

            self.refresh()
        finally:
            self._busy = False

    # ── Render ──────────────────────────────────────────────────────────

    def render(self) -> Text:
        w = self.content_size.width
        h = self.content_size.height
        if w <= 0 or h <= 0:
            return Text()

        # Layout: main bars + 2-row reflection
        refl_phys = min(2, max(0, h // 6))
        bar_phys  = h - refl_phys
        if bar_phys < 4:
            bar_phys  = h
            refl_phys = 0
        bar_virt = bar_phys * 2       # double-res virtual pixels

        # Bar sizing
        if w >= BANDS * 3 - 1:
            bw, gap = 2, 1
        elif w >= BANDS * 2 - 1:
            bw, gap = 1, 1
        else:
            bw, gap = max(1, w // BANDS), 0

        actual_w = bw * BANDS + gap * (BANDS - 1)
        pad_s    = " " * max(0, (w - actual_w) // 2)
        has_pad  = bool(pad_s)

        bands = self._smooth
        peaks = self._peaks
        bg    = BG
        lines: list[Text] = []

        # ── Main bars (half-block double resolution) ────────────────────
        for pr in range(bar_phys):
            line = Text(no_wrap=True)
            if has_pad:
                line.append(pad_s)

            # Two virtual pixels per physical row
            top_vp_from_top = pr * 2
            bot_vp_from_top = pr * 2 + 1
            top_dist = bar_virt - 1 - top_vp_from_top   # from bottom
            bot_dist = bar_virt - 1 - bot_vp_from_top

            for i in range(BANDS):
                if i > 0 and gap:
                    line.append(" " * gap)

                mag      = min(1.0, bands[i])
                peak_val = min(1.0, peaks[i])
                fill     = mag * bar_virt
                peak_pos = peak_val * bar_virt

                top_on = top_dist < fill
                bot_on = bot_dist < fill

                # Peak: thin floating indicator (only when separated from bar)
                top_pk = (not top_on
                          and 0 <= top_dist - peak_pos < 1.0
                          and peak_val > 0.03
                          and peak_pos - fill > 1.5)
                bot_pk = (not bot_on
                          and 0 <= bot_dist - peak_pos < 1.0
                          and peak_val > 0.03
                          and peak_pos - fill > 1.5)

                # Gradient LUT index for each virtual pixel
                gi_t = min(N_GRAD - 1, int(top_dist / max(1, bar_virt - 1) * (N_GRAD - 1)))
                gi_b = min(N_GRAD - 1, int(bot_dist / max(1, bar_virt - 1) * (N_GRAD - 1)))

                # Resolve colors for upper and lower halves
                c_top = _GRAD[i][gi_t] if top_on else (_PEAK[i] if top_pk else bg)
                c_bot = _GRAD[i][gi_b] if bot_on else (_PEAK[i] if bot_pk else bg)

                # Choose optimal character
                if c_top == c_bot:
                    if c_top == bg:
                        line.append(" " * bw)
                    else:
                        line.append("█" * bw, style=c_top)
                else:
                    # ▀ : fg = upper half, bg area = lower half
                    line.append("▀" * bw, style=f"{c_top} on {c_bot}")

            lines.append(line)

        # ── Reflection (subtle, fading) ─────────────────────────────────
        for pr in range(refl_phys):
            line = Text(no_wrap=True)
            if has_pad:
                line.append(pad_s)

            # Fade factor decreases with distance from baseline
            fade = 0.28 * (1.0 - pr / max(1, refl_phys))

            for i in range(BANDS):
                if i > 0 and gap:
                    line.append(" " * gap)

                mag = min(1.0, bands[i])
                # Reflected bar: only the base is visible, fading out
                refl_h = mag * fade * 2.0   # how many virtual pixels of reflection
                top_on = pr * 2 < refl_h
                bot_on = pr * 2 + 1 < refl_h

                rc = _REFL[i]

                if top_on and bot_on:
                    line.append("▀" * bw, style=f"{rc} on {rc}")
                elif top_on:
                    line.append("▀" * bw, style=f"{rc} on {bg}")
                elif bot_on:
                    line.append("▄" * bw, style=f"{rc} on {bg}")
                else:
                    line.append(" " * bw)

            lines.append(line)

        # Join lines
        out = Text(no_wrap=True)
        for idx, ln in enumerate(lines):
            out.append_text(ln)
            if idx < len(lines) - 1:
                out.append("\n")
        return out
