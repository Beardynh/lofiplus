

from __future__ import annotations

from rich.text import Text
from textual.events import Key
from textual.message import Message
from textual.widget import Widget

from lofiplus.core.stations import StationsConfig, Track
from lofiplus.css.palette import ACCENT, BG, BORDER, DIM, MUTED


class TrackList(Widget, can_focus=True):

    DEFAULT_CSS = f"""
    TrackList {{
        height: 1fr;
        min-height: 6;
        background: {BG};
        background-tint: {BG} 0%;
        padding: 1 0;
    }}
    """

    class Selected(Message):
        def __init__(self, name: str, url: str) -> None:
            super().__init__()
            self.name = name
            self.url  = url

    def __init__(
        self,
        custom_stations: list[dict] | None = None,
        favorites: set[str] | None = None,
        **kw,
    ) -> None:
        super().__init__(**kw)
        self._config    = StationsConfig(custom_stations=custom_stations)
        self._favorites = set(favorites or [])
        self._tracks: list[Track] = []
        self._cursor      = 0
        self._view_offset = 0

    def on_mount(self) -> None:
        self._load()

    def _load(self) -> None:
        base = self._config.all_tracks()
        # Mark favorites and reorder: favorites first, then the rest in original order
        for tr in base:
            tr.is_favorite = tr.name in self._favorites
        favs    = [t for t in base if t.is_favorite]
        rest    = [t for t in base if not t.is_favorite]
        self._tracks = favs + rest
        self._cursor = min(self._cursor, max(0, len(self._tracks) - 1))
        self.refresh()

    def refresh_local(self) -> None:
        self._config._last_mtime = 0.0
        self._load()

    def set_favorites(self, favorites: set[str]) -> None:
        self._favorites = set(favorites)
        self._load()

    def current_track(self) -> Track | None:
        if 0 <= self._cursor < len(self._tracks):
            return self._tracks[self._cursor]
        return None

    # ── Rendering with manual viewport ──────────────────────────────

    def _build_lines(self) -> tuple[list[tuple], int]:
        """Build line descriptors and locate the cursor line.

        Returns ``(lines, cursor_line_index)`` where each entry in
        *lines* is one of::

            ("header", text, style)
            ("track",  track_index, Track)
            ("blank",)
            ("dim",    text, style)
        """
        lines: list[tuple] = []
        cursor_line = 0

        favs     = [tr for tr in self._tracks if tr.is_favorite]
        builtins = [tr for tr in self._tracks if not tr.is_favorite and not tr.is_local]
        locals_  = [tr for tr in self._tracks if tr.is_local]

        if favs:
            lines.append(("header", "   ★  FAVORITOS", f"dim {ACCENT}"))
            for tr in favs:
                idx = self._tracks.index(tr)
                if idx == self._cursor:
                    cursor_line = len(lines)
                lines.append(("track", idx, tr))
            lines.append(("blank",))

        lines.append(("header", "   ESTACIONES", f"dim {MUTED}"))
        for tr in builtins:
            idx = self._tracks.index(tr)
            if idx == self._cursor:
                cursor_line = len(lines)
            lines.append(("track", idx, tr))

        lines.append(("blank",))
        lines.append(("header", "   BIBLIOTECA LOCAL", f"dim {MUTED}"))
        if locals_:
            for tr in locals_:
                idx = self._tracks.index(tr)
                if idx == self._cursor:
                    cursor_line = len(lines)
                lines.append(("track", idx, tr))
        else:
            lines.append(("dim", "     Vacía — usa ctrl+/ para descargar", f"dim {DIM}"))

        return lines, cursor_line

    def render(self) -> Text:
        h = self.content_size.height
        if h <= 0:
            return Text()

        lines, cursor_line = self._build_lines()

        # ── Adjust viewport so the cursor is always visible ──────────
        scroll_margin = min(2, h // 3)

        if len(lines) > h:
            if cursor_line < self._view_offset + scroll_margin:
                self._view_offset = cursor_line - scroll_margin
            elif cursor_line >= self._view_offset + h - scroll_margin:
                self._view_offset = cursor_line - h + 1 + scroll_margin
            self._view_offset = max(0, min(self._view_offset, len(lines) - h))
        else:
            self._view_offset = 0

        start = self._view_offset
        end   = start + h
        visible = lines[start:end]

        # ── Render only the visible window ───────────────────────────
        t = Text(no_wrap=True)
        for i, entry in enumerate(visible):
            kind = entry[0]
            if kind == "header":
                t.append(entry[1], style=entry[2])
            elif kind == "blank":
                pass                        # empty line — newline added below
            elif kind == "dim":
                t.append(entry[1], style=entry[2])
            elif kind == "track":
                self._render_track(t, entry[1], entry[2])

            if i < len(visible) - 1:
                t.append("\n")

        return t

    def _render_track(self, t: Text, idx: int, tr: Track) -> None:
        """Append a single track to *t* (no trailing newline)."""
        selected = idx == self._cursor
        prefix   = "▸ " if selected else "  "
        star     = "★ " if tr.is_favorite else ""
        tag      = f" [{tr.tag}]" if tr.tag else ""
        if selected:
            t.append(f"   {prefix}",     style=f"bold {ACCENT}")
            t.append(f"{star}{tr.name}", style=f"bold {ACCENT}")
            t.append(tag,                style=f"dim {MUTED}")
        else:
            color = ACCENT if tr.is_favorite else MUTED
            t.append(f"   {prefix}{star}{tr.name}", style=color)
            t.append(tag,                           style=f"dim {BORDER}")

    # ── Keyboard navigation ──────────────────────────────────────────

    def on_key(self, event: Key) -> None:
        if event.key == "up":
            event.prevent_default()
            self._cursor = max(0, self._cursor - 1)
            self.refresh()
        elif event.key == "down":
            event.prevent_default()
            self._cursor = min(len(self._tracks) - 1, self._cursor + 1)
            self.refresh()
        elif event.key == "enter":
            event.prevent_default()
            tr = self.current_track()
            if tr is not None:
                self.post_message(self.Selected(tr.name, tr.url))
