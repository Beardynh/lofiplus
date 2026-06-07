"""
LofiPlusApp — the main Textual application.

Layout (top-to-bottom):
  ┌─────────────────────────────────────┐
  │  lofiplus  ♪ Track name   vol 70%   │  TitleBar (1 line)
  ├─────────────────────────────────────┤  Rule
  │                                     │
  │          [Spectrum bars]            │  SpectrumWidget (flexible)
  │                                     │
  ├─────────────────────────────────────┤  Rule
  │     ESTACIONES                      │  TrackList (auto)
  │   ▸ Lofi Girl  [live]               │
  │     Chillhop   [live]               │
  │     ...                             │
  ├─────────────────────────────────────┤  Rule
  │  ⬇  URL...                          │  DownloadBar (3)
  ├─────────────────────────────────────┤  Rule
  │  ↑↓ navegar │ enter play │ ...      │  KeyHints (1)
  └─────────────────────────────────────┘
"""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Rule

from lofiplus import __version__
from lofiplus.core import config as user_config
from lofiplus.core.downloader import Downloader
from lofiplus.core.mpv_controller import MpvController
from lofiplus.core.spectrum_source import SpectrumSource
from lofiplus.css.palette import ACCENT, BG, BORDER, MUTED, SURFACE, TEXT
from lofiplus.widgets.changelog_modal import ChangelogModal
from lofiplus.widgets.command_palette import CommandPalette
from lofiplus.widgets.download_bar import DownloadBar
from lofiplus.widgets.key_hints import KeyHints
from lofiplus.widgets.progress_bar import ProgressBar
from lofiplus.widgets.spectrum import SpectrumWidget
from lofiplus.widgets.title_bar import TitleBar
from lofiplus.widgets.track_list import TrackList


class LofiPlusApp(App[None]):

    AUTO_FOCUS = "#tracks"

    CSS = f"""
    Screen {{
        background: {BG};
        color: {TEXT};
    }}

    * {{
        background: {BG};
        background-tint: {BG} 0%;
        scrollbar-background: {BG};
        scrollbar-color: {BORDER};
        scrollbar-color-hover: {MUTED};
        scrollbar-corner-color: {BG};
    }}

    Rule {{
        color: {BORDER};
        background: {BG};
    }}

    KeyHints {{
        background: {SURFACE};
    }}
    """

    BINDINGS = [
        Binding("space",      "toggle_pause",    show=False),
        Binding("s",          "do_stop",         show=False),
        Binding("equal",      "vol_up",          show=False),
        Binding("minus",      "vol_down",        show=False),
        Binding("f",          "toggle_favorite", show=False),
        Binding("slash",      "command_palette", show=False),
        Binding("ctrl+slash", "focus_dl",        show=False),
        Binding("escape",     "blur_dl",         show=False),
        Binding("q",          "quit",            show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config = user_config.load()
        self._mpv    = MpvController()
        self._src    = SpectrumSource()
        self._dl     = Downloader(self._on_dl)
        self._vol    = self._config.volume
        self._track  = ""
        self._pause  = False
        self._favorites: set[str] = set(self._config.favorites)

    # ── Layout ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield TitleBar(id="title")
        yield Rule()
        yield SpectrumWidget(self._src, id="spectrum")
        yield ProgressBar(self._mpv, id="progress")
        yield Rule()
        yield TrackList(
            custom_stations=self._config.custom_stations,
            favorites=self._favorites,
            id="tracks",
        )
        yield Rule()
        yield DownloadBar(id="dl")
        yield Rule()
        yield KeyHints()

    # ── Mount ───────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.title = "lofiplus"
        # Restore volume from saved config
        self._upd()
        if not self._mpv.start():
            self.notify("Could not start mpv — is it installed?", severity="error")
            return
        self._mpv.set_volume(self._vol)
        if not self._src.start():
            self.notify(
                "Loopback unavailable — spectrum is synthetic. "
                "Install sounddevice + a loopback device (BlackHole on macOS).",
                severity="warning", timeout=6,
            )

    # ── Widget messages ─────────────────────────────────────────────────

    def on_track_list_selected(self, msg: TrackList.Selected) -> None:
        self._mpv.play(msg.url, on_status=self._mpv_status)
        self._track = msg.name
        self._pause = False
        self._src.set_playing(True)
        self._upd()

    def on_download_bar_requested(self, msg: DownloadBar.Requested) -> None:
        dl = self.query_one("#dl", DownloadBar)
        if not self._dl.enqueue(msg.url):
            dl.set_status("Download already in progress — wait", "error")
        else:
            dl.set_status("Starting download...", "muted")
        self.query_one("#tracks", TrackList).focus()

    def _on_dl(self, msg: str, kind: str) -> None:
        self.call_from_thread(self._apply_status, msg, kind)

    def _mpv_status(self, msg: str, kind: str) -> None:
        self.call_from_thread(self._apply_status, msg, kind)

    def _apply_status(self, msg: str, kind: str) -> None:
        try:
            self.query_one("#dl", DownloadBar).set_status(msg, kind)
        except Exception:
            pass
        if kind == "ok":
            try:
                self.query_one("#tracks", TrackList).refresh_local()
            except Exception:
                pass

    # ── Actions ─────────────────────────────────────────────────────────

    def action_toggle_pause(self) -> None:
        if self._mpv.is_alive():
            self._mpv.pause()
            self._pause = not self._pause
            self._src.set_playing(not self._pause)
            self._upd()

    def action_do_stop(self) -> None:
        self._mpv.stop()
        self._track = ""
        self._pause = False
        self._src.set_playing(False)
        self._upd()

    def action_vol_up(self) -> None:
        self._vol = min(100, self._vol + 5)
        self._mpv.set_volume(self._vol)
        self._upd()

    def action_vol_down(self) -> None:
        self._vol = max(0, self._vol - 5)
        self._mpv.set_volume(self._vol)
        self._upd()

    def action_focus_dl(self) -> None:
        self.query_one("#dl", DownloadBar).focus_input()

    def action_blur_dl(self) -> None:
        self.query_one("#dl", DownloadBar).clear()
        self.query_one("#tracks", TrackList).focus()

    def action_toggle_favorite(self) -> None:
        tl = self.query_one("#tracks", TrackList)
        tr = tl.current_track()
        if tr is None:
            return
        if tr.name in self._favorites:
            self._favorites.remove(tr.name)
            self.notify(f"Removed from favorites: {tr.name[:50]}", timeout=2)
        else:
            self._favorites.add(tr.name)
            self.notify(f"★ Favorited: {tr.name[:50]}", timeout=2)
        tl.set_favorites(self._favorites)

    # ── Command palette ────────────────────────────────────────────────

    def action_command_palette(self) -> None:
        """Open the slash command palette."""
        self.push_screen(CommandPalette(), self._on_command_picked)

    def _on_command_picked(self, command: str | None) -> None:
        if command is None:
            return
        handler = {
            "act":   self._cmd_act,
            "help":  self._cmd_help,
            "about": self._cmd_about,
            "clear": self._cmd_clear,
            "quit":  self._cmd_quit,
        }.get(command)
        if handler is not None:
            asyncio.create_task(handler())

    async def _cmd_act(self) -> None:
        from lofiplus.core.updater import is_newer, latest_version
        self.notify("Checking GitHub for updates...", timeout=2)
        info = await asyncio.to_thread(latest_version, True)
        if info is None:
            self.notify("Could not reach GitHub (offline?)", severity="warning")
            return
        if not is_newer(info.version, __version__):
            self.notify(f"You're up to date (v{__version__})")
            return
        await self.push_screen(ChangelogModal(info.tag, info.body, info.html_url))

    async def _cmd_help(self) -> None:
        self.notify(
            "↑↓ navigate · enter play · space pause · =/- volume · "
            "ctrl+/ download · s stop · q quit",
            timeout=8,
        )

    async def _cmd_about(self) -> None:
        from lofiplus import __author__, __repo__
        self.notify(
            f"lofiplus v{__version__} · by {__author__} · {__repo__}",
            timeout=6,
        )

    async def _cmd_clear(self) -> None:
        from lofiplus.core.updater import CACHE_FILE
        CACHE_FILE.unlink(missing_ok=True)
        self.notify("Update cache cleared")

    async def _cmd_quit(self) -> None:
        self.exit()

    def _upd(self) -> None:
        try:
            self.query_one("#title", TitleBar).set_state(
                track=self._track, vol=self._vol, pause=self._pause
            )
        except Exception:
            pass

    # ── Cleanup ─────────────────────────────────────────────────────────

    def on_unmount(self) -> None:
        # Persist state before shutdown
        try:
            self._config.volume      = self._vol
            self._config.last_played = self._track
            self._config.favorites   = sorted(self._favorites)
            user_config.save(self._config)
        except Exception:
            pass
        self._src.stop()
        self._mpv.quit()
