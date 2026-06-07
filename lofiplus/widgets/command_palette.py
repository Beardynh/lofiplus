

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Static

from lofiplus.css.palette import ACCENT, BG, BORDER, MUTED, SURFACE, TEXT


@dataclass
class Command:
    name: str           # "act" — typed without slash
    label: str          # display name in the palette
    description: str    # one-liner help


# Registry — single source of truth for available commands
COMMANDS: list[Command] = [
    Command("act",      "/act",      "Check for updates and view changelog"),
    Command("help",     "/help",     "Show keyboard shortcuts"),
    Command("about",    "/about",    "App version and credits"),
    Command("clear",    "/clear",    "Clear update cache"),
    Command("quit",     "/quit",     "Exit lofiplus"),
]


class CommandSelected(Message):
    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command


class _CommandList(Widget):
    """Custom-rendered list of matching commands."""

    DEFAULT_CSS = f"""
    _CommandList {{
        height: auto;
        max-height: 12;
        background: {SURFACE};
        background-tint: {BG} 0%;
        padding: 0 1;
    }}
    """

    def __init__(self) -> None:
        super().__init__()
        self._matches: list[Command] = list(COMMANDS)
        self._cursor = 0

    def filter(self, query: str) -> None:
        q = query.lstrip("/").lower().strip()
        if not q:
            self._matches = list(COMMANDS)
        else:
            self._matches = [c for c in COMMANDS if q in c.name or q in c.label.lower()]
        self._cursor = 0
        self.refresh()

    def move(self, delta: int) -> None:
        if not self._matches:
            return
        self._cursor = (self._cursor + delta) % len(self._matches)
        self.refresh()

    def selected(self) -> Command | None:
        if not self._matches:
            return None
        return self._matches[self._cursor]

    def render(self) -> Text:
        t = Text(no_wrap=True, overflow="ellipsis")
        if not self._matches:
            t.append("  no matches\n", style=f"dim {MUTED}")
            return t
        for i, cmd in enumerate(self._matches):
            selected = i == self._cursor
            prefix = "▸ " if selected else "  "
            if selected:
                t.append(f"  {prefix}", style=f"bold {ACCENT}")
                t.append(f"{cmd.label}", style=f"bold {ACCENT}")
                t.append(f"   {cmd.description}\n", style=MUTED)
            else:
                t.append(f"  {prefix}{cmd.label}", style=TEXT)
                t.append(f"   {cmd.description}\n", style=f"dim {MUTED}")
        return t


class CommandPalette(ModalScreen[str | None]):
    """Modal overlay with a filterable list of slash commands."""

    DEFAULT_CSS = f"""
    CommandPalette {{
        align: center top;
        background: rgba(0, 0, 0, 0.4);
    }}
    CommandPalette #palette-box {{
        width: 60;
        max-width: 90%;
        margin-top: 5;
        background: {SURFACE};
        background-tint: {BG} 0%;
        border: round {BORDER};
        padding: 1 1;
        height: auto;
    }}
    CommandPalette Input {{
        background: {BG};
        background-tint: {BG} 0%;
        color: {TEXT};
        border: none;
        padding: 0 1;
        height: 1;
        margin-bottom: 1;
    }}
    CommandPalette Input:focus {{
        background: {BG};
        background-tint: {BG} 0%;
        border: none;
    }}
    CommandPalette #palette-hint {{
        height: 1;
        color: {MUTED};
        padding: 1 1 0 1;
    }}
    """

    BINDINGS = [
        ("escape", "dismiss", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="palette-box"):
            yield Input(placeholder="Type a command (e.g. act, help)...", id="palette-input")
            yield _CommandList()
            yield Static("↑↓ select  ·  enter run  ·  esc cancel", id="palette-hint")

    def on_mount(self) -> None:
        self.query_one("#palette-input", Input).focus()

    @on(Input.Changed, "#palette-input")
    def _on_change(self, event: Input.Changed) -> None:
        self.query_one(_CommandList).filter(event.value)

    @on(Input.Submitted, "#palette-input")
    def _on_submit(self, event: Input.Submitted) -> None:
        cmd = self.query_one(_CommandList).selected()
        if cmd is not None:
            self.dismiss(cmd.name)

    def on_key(self, event: Key) -> None:
        if event.key == "down":
            event.prevent_default()
            self.query_one(_CommandList).move(1)
        elif event.key == "up":
            event.prevent_default()
            self.query_one(_CommandList).move(-1)

    def action_dismiss(self) -> None:
        self.dismiss(None)
