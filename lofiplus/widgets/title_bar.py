
from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from lofiplus.css.palette import ACCENT, BG, MUTED


class TitleBar(Widget):
    DEFAULT_CSS = f"TitleBar {{ height: 1; background: {BG}; padding: 0 2; background-tint: {BG} 0%; }}"

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self._track = ""
        self._vol   = 70
        self._pause = False

    def set_state(self, track: str = "", vol: int = 70, pause: bool = False) -> None:
        self._track = track
        self._vol   = vol
        self._pause = pause
        self.refresh()

    def render(self) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        t.append("  lofiplus", style=f"bold {ACCENT}")
        if self._track:
            icon = "⏸" if self._pause else "♪"
            t.append(f"  {icon} {self._track}", style=MUTED)
        t.append(f"  vol {self._vol}%", style=MUTED)
        return t
