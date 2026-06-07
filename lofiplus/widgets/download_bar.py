
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static

from lofiplus.css.palette import ACCENT, BG, ERROR, MUTED, SUCCESS, TEXT


class DownloadBar(Widget):
    DEFAULT_CSS = f"""
    DownloadBar {{
        height: 3;
        background: {BG};
        background-tint: {BG} 0%;
        padding: 0 2;
    }}
    DownloadBar #dl-row {{
        height: 1;
        margin-top: 1;
        layout: horizontal;
    }}
    DownloadBar #dl-prefix {{
        width: 4;
        height: 1;
        color: {ACCENT};
        background: {BG};
    }}
    DownloadBar #dl-input {{
        width: 1fr;
        height: 1;
        background: {BG};
        background-tint: {BG} 0%;
        color: {TEXT};
        border: none;
        padding: 0;
    }}
    DownloadBar #dl-input:focus {{
        border: none;
        background: {BG};
        background-tint: {BG} 0%;
    }}
    DownloadBar #dl-status {{
        height: 1;
        padding: 0 4;
        background: {BG};
        color: {MUTED};
    }}
    """

    class Requested(Message):
        def __init__(self, url: str) -> None:
            super().__init__()
            self.url = url

    def compose(self) -> ComposeResult:
        with Horizontal(id="dl-row"):
            yield Static("⬇  ", id="dl-prefix")
            yield Input(placeholder="URL de YouTube o stream de audio...", id="dl-input")
        yield Static("", id="dl-status")

    def focus_input(self) -> None:
        self.query_one("#dl-input", Input).focus()

    def set_status(self, msg: str, kind: str = "muted") -> None:
        color = {"ok": SUCCESS, "error": ERROR, "muted": MUTED}.get(kind, MUTED)
        try:
            self.query_one("#dl-status", Static).update(Text.from_markup(f"[{color}]{msg}[/]"))
        except Exception:
            pass

    def clear(self) -> None:
        try:
            self.query_one("#dl-input", Input).value = ""
            self.query_one("#dl-status", Static).update("")
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        url = event.value.strip()
        if url:
            self.post_message(self.Requested(url))
            event.input.value = ""
