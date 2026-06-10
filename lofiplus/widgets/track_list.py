

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
        # Search mode: None = inactive, "" or text = active filter (key: b)
        self._search: str | None = None

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
        """Track under the cursor, or None when the list is empty."""
        if 0 <= self._cursor < len(self._tracks):
            return self._tracks[self._cursor]
        return None

    # ── Search filter ────────────────────────────────────────────────

    @staticmethod
    def _is_subsequence(query: str, name: str) -> bool:
        """Case-insensitive subsequence match: all query chars appear in order."""
        it = iter(name.lower())
        return all(c in it for c in query.lower())

    def _match_indices(self) -> list[int]:
        """Indices into self._tracks that pass the active search filter."""
        if not self._search:
            return list(range(len(self._tracks)))
        return [
            i for i, tr in enumerate(self._tracks)
            if self._is_subsequence(self._search, tr.name)
        ]

    def _snap_cursor_to_match(self) -> None:
        matches = self._match_indices()
        if matches and self._cursor not in matches:
            self._cursor = matches[0]

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
        visible = set(self._match_indices())

        favs     = [(i, tr) for i, tr in enumerate(self._tracks) if tr.is_favorite and i in visible]
        builtins = [(i, tr) for i, tr in enumerate(self._tracks)
                    if not tr.is_favorite and not tr.is_local and i in visible]
        locals_  = [(i, tr) for i, tr in enumerate(self._tracks) if tr.is_local and i in visible]

        if self._search is not None:
            n = len(visible)
            lines.append((
                "header",
                f"   buscar: {self._search}▌   ({n} resultado{'s' if n != 1 else ''} · esc salir)",
                f"bold {ACCENT}",
            ))
            lines.append(("blank",))

        if favs:
            lines.append(("header", "   ★  FAVORITOS", f"dim {ACCENT}"))
            for idx, tr in favs:
                if idx == self._cursor:
                    cursor_line = len(lines)
                lines.append(("track", idx, tr))
            lines.append(("blank",))

        if builtins or self._search is None:
            lines.append(("header", "   ESTACIONES", f"dim {MUTED}"))
            for idx, tr in builtins:
                if idx == self._cursor:
                    cursor_line = len(lines)
                lines.append(("track", idx, tr))

        if locals_ or self._search is None:
            lines.append(("blank",))
            lines.append(("header", "   BIBLIOTECA LOCAL", f"dim {MUTED}"))
            if locals_:
                for idx, tr in locals_:
                    if idx == self._cursor:
                        cursor_line = len(lines)
                    lines.append(("track", idx, tr))
            elif self._search is None:
                lines.append(("dim", "     Vacía — usa ctrl+/ para descargar", f"dim {DIM}"))

        if self._search is not None and not visible:
            lines.append(("dim", "     Sin coincidencias", f"dim {DIM}"))

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
        # ── Search mode key handling ──────────────────────────────────
        if self._search is not None:
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._search = None
                self.refresh()
                return
            if event.key == "backspace":
                event.prevent_default()
                event.stop()
                self._search = self._search[:-1]
                self._snap_cursor_to_match()
                self.refresh()
                return
            if event.is_printable and event.character:
                # stop() keeps app-level bindings (f, q, space, …) from firing
                # while the user is typing a query
                event.prevent_default()
                event.stop()
                self._search += event.character
                self._snap_cursor_to_match()
                self.refresh()
                return
            # up/down/enter fall through to the navigation handlers below
        elif event.key == "b":
            event.prevent_default()
            event.stop()
            self._search = ""
            self.refresh()
            return

        matches = self._match_indices()
        if event.key == "up":
            event.prevent_default()
            if matches:
                prev = [i for i in matches if i < self._cursor]
                self._cursor = prev[-1] if prev else matches[0]
            self.refresh()
        elif event.key == "down":
            event.prevent_default()
            if matches:
                nxt = [i for i in matches if i > self._cursor]
                self._cursor = nxt[0] if nxt else matches[-1]
            self.refresh()
        elif event.key == "enter":
            event.prevent_default()
            tr = self.current_track()
            if tr is not None:
                self._search = None  # exit search mode on selection
                self.post_message(self.Selected(tr.name, tr.url))
                self.refresh()
