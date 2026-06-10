
from __future__ import annotations

import math
import threading
import time
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widget import Widget

from lofiplus.css.palette import ACCENT, BG, BORDER, MUTED, SURFACE

if TYPE_CHECKING:
    from lofiplus.core.mpv_controller import MpvController


def _fmt_time(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        return "0:00"
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    s = s % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


class ProgressBar(Widget):
    DEFAULT_CSS = f"""
    ProgressBar {{
        height: 1;
        background: {BG};
        background-tint: {BG} 0%;
        padding: 0 2;
    }}
    """

    POLL_INTERVAL = 0.5  # seconds between mpv IPC queries

    def __init__(self, mpv: "MpvController", **kw) -> None:
        super().__init__(**kw)
        self._mpv     = mpv
        self._pos     = 0.0
        self._dur     = 0.0
        self._last_poll_time = time.time()
        self._stop_evt = threading.Event()
        self._poll_thread: threading.Thread | None = None

    def on_mount(self) -> None:
        # One persistent poller thread: at most one IPC request in flight,
        # no per-tick thread creation, no check-and-set race on a flag.
        self._stop_evt.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="mpv-progress"
        )
        self._poll_thread.start()
        # Refresh the UI at 15 FPS for smooth interpolation
        self.set_interval(1.0 / 15.0, self.refresh)

    def on_unmount(self) -> None:
        self._stop_evt.set()

    def _poll_loop(self) -> None:
        """Daemon thread: query mpv every POLL_INTERVAL until stopped."""
        while not self._stop_evt.wait(self.POLL_INTERVAL):
            if not self._mpv.is_alive():
                continue
            try:
                pos = self._mpv.get_time_pos()
                dur = self._mpv.get_duration()
            except Exception:
                continue
            try:
                self.app.call_from_thread(self._update, pos, dur)
            except Exception:
                # App is shutting down — stop polling
                return

    def _update(self, pos: float, dur: float) -> None:
        self._pos = pos
        self._dur = dur
        self._last_poll_time = time.time()
        self.refresh()

    def render(self) -> Text:
        w = self.content_size.width
        if w <= 12:
            return Text("", no_wrap=True)

        is_live = (not math.isfinite(self._dur)) or self._dur <= 0.0

        if is_live:
            # LIVE stream / radio: completely static
            pos_str = "0:00"
            right_label = "LIVE"
            bar_width = w - len(pos_str) - len(right_label) - 6
            if bar_width < 4:
                out = Text(no_wrap=True)
                out.append(right_label, style=f"bold {ACCENT}")
                return out

            out = Text(no_wrap=True)
            out.append(pos_str, style=MUTED)
            out.append("  ")
            out.append("─" * bar_width, style=BORDER)
            out.append("  ")
            out.append("● ", style=ACCENT)
            out.append(right_label, style=f"bold {ACCENT}")
            return out

        # Interpolate position if playing a local/custom file with duration
        is_playing = self._mpv.is_alive() and hasattr(self.app, "_pause") and not self.app._pause and getattr(self.app, "_track", "")
        if is_playing and self._dur > 0.0 and self._pos < self._dur:
            elapsed = time.time() - self._last_poll_time
            pos = min(self._dur, self._pos + elapsed)
        else:
            pos = self._pos

        pos_str = _fmt_time(pos)
        dur_str  = _fmt_time(self._dur)
        bar_width = w - len(pos_str) - len(dur_str) - 4
        if bar_width < 4:
            out = Text(no_wrap=True)
            out.append(dur_str, style=MUTED)
            return out

        ratio = max(0.0, min(1.0, pos / self._dur))
        filled = int(ratio * bar_width)

        out = Text(no_wrap=True)
        out.append(pos_str, style=MUTED)
        out.append("  ")
        for i in range(bar_width):
            if i < filled:
                out.append("━", style=ACCENT)
            else:
                out.append("─", style=BORDER)
        out.append("  ")
        out.append(dur_str, style=MUTED)

        return out
