

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
        overflow-y: auto;
        scrollbar-size-vertical: 1;
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
        self._cursor    = 0

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

    def render(self) -> Text:
        t = Text(no_wrap=True)
        favs     = [tr for tr in self._tracks if tr.is_favorite]
        builtins = [tr for tr in self._tracks if not tr.is_favorite and not tr.is_local]
        locals_  = [tr for tr in self._tracks if tr.is_local]

        if favs:
            t.append("   ★  FAVORITOS\n", style=f"dim {ACCENT}")
            for tr in favs:
                idx = self._tracks.index(tr)
                self._row(t, idx, tr)
            t.append("\n")

        t.append("   ESTACIONES\n", style=f"dim {MUTED}")
        for tr in builtins:
            idx = self._tracks.index(tr)
            self._row(t, idx, tr)

        t.append("\n   BIBLIOTECA LOCAL\n", style=f"dim {MUTED}")
        if locals_:
            for tr in locals_:
                idx = self._tracks.index(tr)
                self._row(t, idx, tr)
        else:
            t.append("     Vacía — usa ctrl+/ para descargar\n", style=f"dim {DIM}")
        return t

    def _row(self, t: Text, idx: int, tr: Track) -> None:
        selected = idx == self._cursor
        prefix   = "▸ " if selected else "  "
        star     = "★ " if tr.is_favorite else ""
        tag      = f" [{tr.tag}]" if tr.tag else ""
        if selected:
            t.append(f"   {prefix}",     style=f"bold {ACCENT}")
            t.append(f"{star}{tr.name}", style=f"bold {ACCENT}")
            t.append(tag + "\n",         style=f"dim {MUTED}")
        else:
            color = ACCENT if tr.is_favorite else MUTED
            t.append(f"   {prefix}{star}{tr.name}", style=color)
            t.append(tag + "\n",                    style=f"dim {BORDER}")

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
