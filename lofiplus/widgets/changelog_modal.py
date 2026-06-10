"""Modal that displays a GitHub Release's body as Markdown."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

from lofiplus.css.palette import ACCENT, BG, BORDER, MUTED, SURFACE, TEXT


class ChangelogModal(ModalScreen[None]):

    DEFAULT_CSS = f"""
    ChangelogModal {{
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }}
    ChangelogModal #box {{
        width: 80;
        max-width: 95%;
        height: 30;
        background: {SURFACE};
        background-tint: {BG} 0%;
        border: round {ACCENT};
        padding: 1 2;
    }}
    ChangelogModal #title {{
        color: {ACCENT};
        text-style: bold;
        height: 1;
        margin-bottom: 1;
    }}
    ChangelogModal Markdown {{
        background: {SURFACE};
        background-tint: {BG} 0%;
        color: {TEXT};
        height: 1fr;
    }}
    ChangelogModal #footer {{
        color: {MUTED};
        height: 1;
        margin-top: 1;
    }}
    """

    BINDINGS = [
        Binding("escape", "dismiss"),
        Binding("q",      "dismiss"),
    ]

    def __init__(self, tag: str, body: str, url: str) -> None:
        super().__init__()
        self._tag = tag
        self._url = url
        # The body comes from GitHub (or a local cache file) — pre-flight it
        # so malformed/huge content can't take down the modal.
        safe = body or "*(No release notes provided.)*"
        if len(safe) > 20_000:
            safe = safe[:20_000] + "\n\n*(truncated)*"
        try:
            from markdown_it import MarkdownIt  # textual's own parser
            MarkdownIt().parse(safe)
        except Exception:
            safe = "```text\n" + safe.replace("`", "'") + "\n```"
        self._body = safe

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(f"⬆  New release: {self._tag}", id="title")
            yield Markdown(self._body)
            yield Static(
                f"  Update: lofiplus -a    │    {self._url}    │    esc to close",
                id="footer",
            )

    def action_dismiss(self) -> None:
        self.dismiss(None)
