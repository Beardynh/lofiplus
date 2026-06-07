
from __future__ import annotations

from rich.text import Text
from textual.widget import Widget

from lofiplus.css.palette import BORDER, MUTED, SURFACE, TEXT


class KeyHints(Widget):
    DEFAULT_CSS = f"""
    KeyHints {{
        height: 1;
        background: {SURFACE};
        padding: 0 2;
    }}
    """

    HINTS: list[tuple[str, str]] = [
        ("↑↓",    "navegar"),
        ("enter", "play"),
        ("space", "pausa"),
        ("=/-",   "vol"),
        ("/",     "comandos"),
        ("ctrl+/", "descargar"),
        ("s",     "stop"),
        ("q",     "salir"),
    ]

    def render(self) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        for i, (k, v) in enumerate(self.HINTS):
            if i:
                t.append("  │  ", style=f"dim {BORDER}")
            t.append(k, style=f"bold {TEXT}")
            t.append(f" {v}", style=MUTED)
        return t
