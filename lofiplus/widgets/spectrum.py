"""
Spectrum visualizer — two switchable modes (key: v).

  "aurora"  Smooth mirrored wave drawn on a braille canvas (2×4 sub-cell
            resolution), slow chromatic drift, bright crest line, and a
            white-hot flash on bass beats.

  "bars"    Gradient mirror bars (peak-hold with gravity, reflection) plus
            floating ember particles rising from falling peaks and a beat
            flash on the bar tips.

Shared machinery: frequency-dependent smoothing, bass beat detector,
gradient LUTs regenerated every ~3 s for the chromatic drift.

Memory discipline: braille canvas buffers and the particle pool are
fixed-size and reused; LUTs are rebuilt in place.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widget import Widget

from lofiplus.css.palette import BG
from lofiplus.widgets.braille import BrailleCanvas

if TYPE_CHECKING:
    from lofiplus.core.spectrum_source import SpectrumSource

BANDS  = 32
FPS    = 30
N_GRAD = 24          # pre-computed gradient resolution per band

MODES = ("aurora", "bars")
MAX_PARTICLES = 24   # fixed pool — slots are reused, never reallocated

# Chromatic drift: full breathe cycle length and LUT rebuild cadence
DRIFT_PERIOD_S   = 45.0
LUT_REBUILD_EVERY = 90   # frames (3 s at 30 FPS)


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


def _build_gradient_row(base: str) -> list[str]:
    """24-step vertical gradient for one band: dark base → bright tip glow."""
    dark = _lerp(base, BG, 0.62)
    brt  = _lerp(base, "#ffffff", 0.20)
    tip  = _lerp(base, "#ffffff", 0.40)
    row: list[str] = []
    for j in range(N_GRAD):
        t = j / (N_GRAD - 1)
        if t < 0.55:
            row.append(_lerp(dark, base, t / 0.55))
        elif t < 0.82:
            row.append(_lerp(base, brt, (t - 0.55) / 0.27))
        else:
            row.append(_lerp(brt, tip, (t - 0.82) / 0.18))
    return row


# ── Widget ─────────────────────────────────────────────────────────────

class SpectrumWidget(Widget):
    DEFAULT_CSS = f"""
    SpectrumWidget {{
        height: 1fr;
        max-height: 14;
        min-height: 4;
        background: {BG};
        background-tint: {BG} 0%;
        padding: 0 1;
    }}
    """

    def __init__(self, source: "SpectrumSource", mode: str = "aurora", **kw) -> None:
        super().__init__(**kw)
        self._src    = source
        self._mode   = mode if mode in MODES else "aurora"
        self._smooth = [0.0] * BANDS
        self._wave   = [0.0] * BANDS      # heavier smoothing for aurora
        self._peaks  = [0.0] * BANDS
        self._p_vel  = [0.0] * BANDS
        self._busy   = False
        self._frame  = 0

        # Beat detector
        self._pulse    = 0.0
        self._bass_avg = 0.0
        self._beat_cd  = 0

        # Instance LUTs (rebuilt in place by the chromatic drift)
        self._grad: list[list[str]] = [_build_gradient_row(c) for c in _BASE]
        self._grad_hot: list[list[str]] = [
            [_lerp(c, "#ffffff", 0.35) for c in row] for row in self._grad
        ]
        self._peakc: list[str] = [_lerp(c, "#ffffff", 0.55) for c in _BASE]
        self._reflc: list[str] = [_lerp(c, BG, 0.78) for c in _BASE]

        # Braille canvas for aurora mode (buffers reused across frames)
        self._canvas = BrailleCanvas()

        # Ember particle pool — parallel fixed-size arrays, slots reused
        self._pt_alive = [False] * MAX_PARTICLES
        self._pt_band  = [0]     * MAX_PARTICLES
        self._pt_y     = [0.0]   * MAX_PARTICLES   # normalized 0(base)..1(top)
        self._pt_vy    = [0.0]   * MAX_PARTICLES
        self._pt_life  = [0]     * MAX_PARTICLES

    # ── Mode switching ───────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode in MODES:
            self._mode = mode
            self.refresh()

    def cycle_mode(self) -> str:
        idx = MODES.index(self._mode)
        self._mode = MODES[(idx + 1) % len(MODES)]
        self.refresh()
        return self._mode

    # ── Lifecycle ────────────────────────────────────────────────────────

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
                # Aurora wave: extra inertia so the curve flows, not jumps
                self._wave[i] = self._wave[i] * 0.70 + self._smooth[i] * 0.30

            # Peak hold with gravity
            for i in range(BANDS):
                v = self._smooth[i]
                if v >= self._peaks[i]:
                    self._peaks[i] = v
                    self._p_vel[i] = 0.0
                else:
                    self._p_vel[i] += 0.004
                    self._peaks[i] = max(0.0, self._peaks[i] - self._p_vel[i])

            self._detect_beat()
            if self._mode == "bars":
                self._update_particles()
            self._frame += 1
            if self._frame % LUT_REBUILD_EVERY == 0:
                self._rebuild_luts()

            self.refresh()
        finally:
            self._busy = False

    def _detect_beat(self) -> None:
        bass = sum(self._smooth[0:6]) / 6.0
        self._bass_avg = self._bass_avg * 0.96 + bass * 0.04
        if self._beat_cd > 0:
            self._beat_cd -= 1
        if (bass > self._bass_avg * 1.35 and bass > 0.12
                and self._beat_cd == 0):
            self._pulse   = 1.0
            self._beat_cd = 8
        self._pulse *= 0.85

    def _rebuild_luts(self) -> None:
        """Chromatic drift: slowly breathe each band's hue toward its
        neighbor 6 bands over, cycling every DRIFT_PERIOD_S seconds."""
        phase = (self._frame / FPS) / DRIFT_PERIOD_S * 2.0 * math.pi
        s = 0.5 + 0.5 * math.sin(phase)          # 0..1
        for i in range(BANDS):
            tinted = _lerp(_BASE[i], _BASE[(i + 6) % BANDS], 0.45 * s)
            row = _build_gradient_row(tinted)
            grad, hot = self._grad[i], self._grad_hot[i]
            for j in range(N_GRAD):
                grad[j] = row[j]
                hot[j]  = _lerp(row[j], "#ffffff", 0.35)
            self._peakc[i] = _lerp(tinted, "#ffffff", 0.55)
            self._reflc[i] = _lerp(tinted, BG, 0.78)

    # ── Ember particles (bars mode) ──────────────────────────────────────

    def _update_particles(self) -> None:
        # Advance live particles
        for k in range(MAX_PARTICLES):
            if not self._pt_alive[k]:
                continue
            self._pt_y[k]    += self._pt_vy[k]
            self._pt_life[k] -= 1
            if self._pt_life[k] <= 0 or self._pt_y[k] > 1.08:
                self._pt_alive[k] = False
        # Spawn from peaks that are clearly falling
        for i in range(BANDS):
            if (self._peaks[i] > 0.45 and self._p_vel[i] > 0.006
                    and random.random() < 0.10):
                for k in range(MAX_PARTICLES):
                    if not self._pt_alive[k]:
                        self._pt_alive[k] = True
                        self._pt_band[k]  = i
                        self._pt_y[k]     = self._peaks[i]
                        self._pt_vy[k]    = 0.015 + random.random() * 0.012
                        self._pt_life[k]  = 22
                        break

    # ── Render dispatch ──────────────────────────────────────────────────

    def render(self) -> Text:
        w = self.content_size.width
        h = self.content_size.height
        if w <= 0 or h <= 0:
            return Text()
        if self._mode == "aurora":
            return self._render_aurora(w, h)
        return self._render_bars(w, h)

    # ── Mode: aurora (braille wave) ──────────────────────────────────────

    def _render_aurora(self, w: int, h: int) -> Text:
        cv = self._canvas
        cv.resize(w, h)
        cv.clear()

        W = cv.width_px
        H = cv.height_px
        if W <= 1 or H <= 1:
            return Text()

        center   = (H - 1) / 2.0
        half_max = H / 2.0 - 0.5
        wave     = self._wave
        pulse    = self._pulse

        # Fill mirrored columns with cosine-interpolated band heights
        for px in range(W):
            f  = px / (W - 1) * (BANDS - 1)
            i0 = int(f)
            i1 = min(BANDS - 1, i0 + 1)
            c  = (1.0 - math.cos((f - i0) * math.pi)) / 2.0
            v  = wave[i0] * (1.0 - c) + wave[i1] * c
            amp = v * half_max
            if amp < 0.4:
                cv.set(px, int(center))          # standby: thin center line
                continue
            cv.vline(px, int(center - amp), int(center + amp + 0.999))

        # Color cells: gradient by distance from center, crest highlighted
        grad, peakc = self._grad, self._peakc
        hot = pulse > 0.25
        half_cells = h / 2.0
        for cx in range(w):
            band = int(cx / max(1, w - 1) * (BANDS - 1))
            first = -1
            last  = -1
            for cy in range(h):
                if not cv.cell_filled(cx, cy):
                    continue
                if first < 0:
                    first = cy
                last = cy
                d  = abs((cy + 0.5) - half_cells) / half_cells   # 0 centro → 1 borde
                gi = min(N_GRAD - 1, int(d * (N_GRAD - 1)))
                color = grad[band][gi]
                if hot:
                    color = _lerp(color, "#ffffff", 0.30 * pulse)
                cv.set_cell_color(cx, cy, color)
            # Bright crest on the outermost cells of the wave
            if first >= 0 and last > first:
                cv.set_cell_color(cx, first, peakc[band])
                cv.set_cell_color(cx, last,  peakc[band])

        return cv.render()

    # ── Mode: bars (gradient mirror bars + particles) ────────────────────

    def _render_bars(self, w: int, h: int) -> Text:
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
        grad  = self._grad
        ghot  = self._grad_hot
        pkc   = self._peakc
        pulse = self._pulse
        flash = pulse > 0.30
        lines: list[Text] = []

        # Particle overlay: {(physical_row, band) → (char, color)}
        overlay: dict[tuple[int, int], tuple[str, str]] = {}
        for k in range(MAX_PARTICLES):
            if not self._pt_alive[k]:
                continue
            i  = self._pt_band[k]
            pr = (bar_virt - 1 - int(self._pt_y[k] * (bar_virt - 1))) // 2
            if 0 <= pr < bar_phys:
                frac = self._pt_life[k] / 22.0
                ch   = "•" if frac > 0.6 else ("∙" if frac > 0.3 else "·")
                overlay[(pr, i)] = (ch, _lerp(pkc[i], bg, 1.0 - frac))

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

                # Beat flash: the top 20 % of a lit bar goes white-hot
                lut_t = ghot[i] if (flash and top_dist > fill * 0.80) else grad[i]
                lut_b = ghot[i] if (flash and bot_dist > fill * 0.80) else grad[i]

                # Resolve colors for upper and lower halves
                c_top = lut_t[gi_t] if top_on else (pkc[i] if top_pk else bg)
                c_bot = lut_b[gi_b] if bot_on else (pkc[i] if bot_pk else bg)

                # Choose optimal character
                if c_top == c_bot:
                    if c_top == bg:
                        # Empty cell — ember particle overlay goes here
                        part = overlay.get((pr, i))
                        if part is not None:
                            ch, color = part
                            line.append(ch + " " * (bw - 1), style=color)
                        else:
                            line.append(" " * bw)
                    else:
                        line.append("█" * bw, style=c_top)
                else:
                    # ▀ : fg = upper half, bg area = lower half
                    line.append("▀" * bw, style=f"{c_top} on {c_bot}")

            lines.append(line)

        # ── Reflection (subtle, fading) ─────────────────────────────────
        reflc = self._reflc
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

                rc = reflc[i]

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
