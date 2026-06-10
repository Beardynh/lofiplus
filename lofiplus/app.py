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
from lofiplus.core.audio_router import AudioRouter
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
        Binding("f",          "toggle_favorite",  show=False),
        Binding("v",          "cycle_visualizer", show=False),
        Binding("slash",      "command_palette",  show=False),
        Binding("ctrl+slash", "focus_dl",        show=False),
        Binding("escape",     "blur_dl",         show=False),
        Binding("q",          "quit",            show=False),
    ]

    # Backoff schedule for stream auto-reconnect (D2)
    RECONNECT_DELAYS = (2.0, 5.0, 10.0)

    def __init__(self) -> None:
        super().__init__()
        self._config = user_config.load()
        self._router = AudioRouter()
        self._mpv    = MpvController()
        self._src    = SpectrumSource()
        self._dl     = Downloader(self._on_dl)
        self._vol    = self._config.volume
        self._track  = ""
        self._pause  = False
        self._favorites: set[str] = set(self._config.favorites)
        # Now Playing metadata (D1)
        self._now_playing = ""
        # Auto-reconnect state (D2)
        self._current_url       = ""
        self._user_stopped      = False
        self._reconnect_attempt = 0

    # ── Layout ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield TitleBar(id="title")
        yield Rule()
        yield SpectrumWidget(self._src, mode=self._config.visualizer, id="spectrum")
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
        # Unsolicited mpv events (end-file → auto-reconnect, file-loaded → reset)
        self._mpv.set_event_callback(self._on_mpv_event)
        # Now Playing: poll stream metadata every 5 s
        self.set_interval(5.0, self._poll_now_playing)

        # Isolated audio route: mpv → null sink → loopback → speakers,
        # so the visualizer only ever sees lofiplus' own audio.
        sink = self._router.setup()
        audio_device = f"pulse/{sink}" if sink else None
        monitor      = self._router.monitor_name if sink else None
        if sink is None:
            self.notify(
                "Audio sin aislar — el espectro reaccionará a todo el sistema",
                severity="warning", timeout=5,
            )

        if not self._mpv.start(audio_device=audio_device):
            self.notify("Could not start mpv — is it installed?", severity="error")
            return
        self._mpv.set_volume(self._vol)
        # start() returns the active mode: "cava" | "loopback" | None (synthetic)
        mode = self._src.start(monitor=monitor)
        if mode is None:
            self.notify(
                "Loopback unavailable — spectrum is synthetic. "
                "Install sounddevice + a loopback device (BlackHole on macOS).",
                severity="warning", timeout=6,
            )

    # ── Widget messages ─────────────────────────────────────────────────

    def on_track_list_selected(self, msg: TrackList.Selected) -> None:
        self._mpv.play(msg.url, on_status=self._mpv_status)
        # Restore volume – mpv may have been restarted by _ensure_alive()
        self._mpv.set_volume(self._vol)
        self._track = msg.name
        self._pause = False
        # Reset reconnect + now-playing state for the new selection
        self._current_url       = msg.url
        self._user_stopped      = False
        self._reconnect_attempt = 0
        self._now_playing       = ""
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
        try:
            self.call_from_thread(self._apply_status, msg, kind)
        except Exception:
            pass  # app shutting down

    def _mpv_status(self, msg: str, kind: str) -> None:
        try:
            self.call_from_thread(self._apply_status, msg, kind)
        except Exception:
            pass  # app shutting down

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
        self._user_stopped = True  # set BEFORE stop() so end-file is ignored
        self._mpv.stop()
        self._track       = ""
        self._now_playing = ""
        self._current_url = ""
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

    def action_cycle_visualizer(self) -> None:
        spec = self.query_one("#spectrum", SpectrumWidget)
        new_mode = spec.cycle_mode()
        self._config.visualizer = new_mode
        self.notify(f"Visualizador: {new_mode}", timeout=2)

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
            # run_worker uses the app's own event loop and cancels the
            # coroutine cleanly on shutdown (create_task from a sync
            # callback can race the loop teardown)
            self.run_worker(handler(), exclusive=False)

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
        # Compose display: "Now Playing — Station" when stream metadata is known
        display = self._track
        if self._now_playing and self._now_playing != self._track:
            display = f"{self._now_playing} — {self._track}"
        try:
            self.query_one("#title", TitleBar).set_state(
                track=display, vol=self._vol, pause=self._pause
            )
        except Exception:
            pass

    # ── Now Playing (D1) ────────────────────────────────────────────────

    def _poll_now_playing(self) -> None:
        if not self._track or not self._mpv.is_alive():
            return
        # IPC is blocking — query in a thread worker; exclusive group avoids
        # piling up if mpv is slow to answer
        self.run_worker(
            self._fetch_now_playing, thread=True,
            exclusive=True, group="now-playing",
        )

    def _fetch_now_playing(self) -> None:
        title = self._mpv.get_media_title()
        try:
            self.call_from_thread(self._apply_now_playing, title)
        except Exception:
            pass  # app shutting down

    def _apply_now_playing(self, title: str) -> None:
        title = " ".join(title.split())  # collapse whitespace/newlines
        # mpv reports the URL itself when the stream has no metadata
        if not title or title.startswith(("http://", "https://")):
            title = ""
        if title != self._now_playing:
            self._now_playing = title
            self._upd()

    # ── Auto-reconnect (D2) ─────────────────────────────────────────────

    def _on_mpv_event(self, msg: dict) -> None:
        """Unsolicited mpv events — runs on the IPC reader thread."""
        event = msg.get("event")
        try:
            if event == "end-file":
                self.call_from_thread(self._handle_end_file, str(msg.get("reason", "")))
            elif event == "file-loaded":
                self.call_from_thread(self._reset_reconnect)
        except Exception:
            pass  # app shutting down

    def _reset_reconnect(self) -> None:
        self._reconnect_attempt = 0

    def _handle_end_file(self, reason: str) -> None:
        # Only error/eof are interesting: "stop" fires for our own stop and
        # for loadfile-replace; "quit"/"redirect" are not stream drops.
        if reason not in ("error", "eof"):
            return
        if self._user_stopped or not self._current_url:
            return
        # A local file reaching eof simply finished — clear the display
        if "://" not in self._current_url:
            self._track       = ""
            self._now_playing = ""
            self._current_url = ""
            self._src.set_playing(False)
            self._upd()
            return
        if self._reconnect_attempt >= len(self.RECONNECT_DELAYS):
            self._apply_status("Stream dropped — gave up after 3 attempts", "error")
            self._reconnect_attempt = 0
            self._src.set_playing(False)
            return
        delay = self.RECONNECT_DELAYS[self._reconnect_attempt]
        self._reconnect_attempt += 1
        self._apply_status(
            f"Stream dropped — reconnecting in {delay:.0f}s "
            f"(attempt {self._reconnect_attempt}/{len(self.RECONNECT_DELAYS)})",
            "muted",
        )
        self.set_timer(delay, self._do_reconnect)

    def _do_reconnect(self) -> None:
        if self._user_stopped or not self._current_url:
            return
        self._mpv.play(self._current_url, on_status=self._mpv_status)
        self._mpv.set_volume(self._vol)

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
        self._dl.stop()
        self._src.stop()
        self._mpv.quit()
        # After mpv: the sink must outlive the process writing to it
        self._router.teardown()
