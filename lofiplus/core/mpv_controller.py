r"""
Cross-platform mpv controller via IPC.

- Linux/macOS: Unix domain socket at /tmp/lofiplus_<pid>.sock
- Windows:     Named pipe at \\.\pipe\lofiplus_<pid>

mpv runs as a separate process with --no-video --idle=yes.
JSON commands are sent over the IPC channel; responses and events are
parsed by a daemon reader thread.

Memory management:
- Read buffer is consumed line-by-line; emergency reset at 64 KB
- self._pending is cleared in finally to avoid orphaned Events
- request_id is a simple integer counter
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

# ─── Platform detection ──────────────────────────────────────────────────────
IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS   = sys.platform == "darwin"
IS_LINUX   = sys.platform.startswith("linux")

# Default audio output per platform
if IS_LINUX:
    DEFAULT_AO = "pipewire,pulse,alsa"
elif IS_MACOS:
    DEFAULT_AO = "coreaudio"
elif IS_WINDOWS:
    DEFAULT_AO = "wasapi"
else:
    DEFAULT_AO = ""

# IPC path
if IS_WINDOWS:
    IPC_PATH_TPL = r"\\.\pipe\lofiplus_{pid}"
else:
    IPC_PATH_TPL = "/tmp/lofiplus_{pid}.sock"

ALLOWED_LOCAL_EXTS = {".mp4", ".mp3", ".webm", ".wav", ".aiff", ".flac", ".aac", ".mov"}


class MpvController:
    """Launches mpv and controls it via IPC (Unix socket on Linux/macOS, named pipe on Windows)."""

    def __init__(self) -> None:
        self._ipc_path  = IPC_PATH_TPL.format(pid=os.getpid())
        self._proc:    subprocess.Popen | None = None
        self._conn = None  # socket.socket on POSIX, file handle on Windows
        self._rid       = 0
        self._lock      = threading.Lock()
        self._running   = False
        self._reader: threading.Thread | None = None
        # _pending/_results are shared between _send() callers and the reader
        # thread — every access goes through self._lock (see _send/_read_loop)
        self._pending: dict[int, threading.Event] = {}
        self._results: dict[int, Any] = {}
        self._start_lock = threading.Lock()  # serialise start / restart
        # Remembered across restarts so _ensure_alive() rebuilds the same route
        self._audio_device: str | None = None
        # Optional callback for unsolicited mpv events (e.g. end-file).
        # NOTE: invoked on the reader thread — UI code must re-dispatch
        # via app.call_from_thread.
        self._event_cb: Callable[[dict], None] | None = None

    @property
    def ipc_path(self) -> str:
        return self._ipc_path

    def set_event_callback(self, cb: Callable[[dict], None] | None) -> None:
        """Register a callback for unsolicited mpv events (runs on reader thread)."""
        self._event_cb = cb

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self, audio_device: str | None = None) -> bool:
        """Launch mpv and connect to the IPC channel. Returns True on success.

        audio_device: optional mpv device string (e.g. "pulse/lofiplus_123")
        to route audio into an isolated sink. Remembered for restarts.
        """
        if audio_device is not None:
            self._audio_device = audio_device

        args = [
            "mpv",
            "--no-video",
            "--idle=yes",
            f"--input-ipc-server={self._ipc_path}",
            "--volume=70",
            "--quiet",
            "--really-quiet",
        ]
        if self._audio_device:
            # Isolated route: force the pulse AO at the dedicated sink
            args += ["--ao=pulse", f"--audio-device={self._audio_device}"]
        else:
            args += [f"--ao={DEFAULT_AO}"]

        try:
            kwargs: dict[str, Any] = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if IS_WINDOWS:
                # No console window on Windows
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            self._proc = subprocess.Popen(args, **kwargs)
        except FileNotFoundError:
            return False

        # Wait for IPC endpoint to appear (max 5s)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if IS_WINDOWS:
                if Path(self._ipc_path.replace(r"\\.\pipe\\", r"\\.\pipe\\")).exists() or self._try_connect_pipe():
                    break
            else:
                if Path(self._ipc_path).exists():
                    break
            time.sleep(0.05)
        else:
            self.quit()
            return False

        # Connect
        if IS_WINDOWS:
            if self._conn is None and not self._try_connect_pipe():
                self.quit()
                return False
        else:
            import socket
            self._conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                self._conn.connect(self._ipc_path)
            except OSError:
                self.quit()
                return False

        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True, name="mpv-reader")
        self._reader.start()
        return True

    def _try_connect_pipe(self) -> bool:
        """Windows: open the named pipe in binary read/write mode."""
        try:
            self._conn = open(self._ipc_path, "r+b", buffering=0)
            return True
        except OSError:
            self._conn = None
            return False

    def quit(self) -> None:
        """Stop mpv and clean up."""
        self._running = False
        # Wake any threads blocked in _send()
        with self._lock:
            for ev in list(self._pending.values()):
                ev.set()
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self._proc.kill()
                except OSError:
                    pass
            self._proc = None
        if not IS_WINDOWS:
            Path(self._ipc_path).unlink(missing_ok=True)
        with self._lock:
            self._pending.clear()
            self._results.clear()

    def is_alive(self) -> bool:
        return self._running and self._proc is not None and self._proc.poll() is None

    # ── IPC reader loop (daemon thread) ──────────────────────────────────

    def _read_loop(self) -> None:
        buf = b""
        try:
            while self._running and self._conn is not None:
                try:
                    if IS_WINDOWS:
                        data = self._conn.read(4096)
                    else:
                        data = self._conn.recv(4096)
                    if not data:
                        break
                    buf += data
                    if len(buf) > 65536:
                        buf = b""
                        continue
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        rid = msg.get("request_id")
                        if rid is not None:
                            # Atomic check-and-store: if the caller already
                            # timed out and removed its entry, drop the data
                            # (otherwise _results leaks orphan entries).
                            with self._lock:
                                ev = self._pending.get(rid)
                                if ev is not None:
                                    self._results[rid] = msg.get("data")
                                    ev.set()
                        elif "event" in msg and self._event_cb is not None:
                            try:
                                self._event_cb(msg)
                            except Exception:
                                pass
                except (OSError, ValueError):
                    break
        finally:
            # Mark connection as dead so _send() fails fast
            # instead of blocking on the 2 s timeout.
            self._running = False
            # Wake every caller still waiting for a response.
            with self._lock:
                for ev in list(self._pending.values()):
                    ev.set()

    # ── Send commands ────────────────────────────────────────────────────

    def _send(self, command: list[Any], timeout: float = 2.0) -> Any:
        if self._conn is None or not self._running:
            return None
        ev = threading.Event()
        with self._lock:
            self._rid += 1
            rid = self._rid
            self._pending[rid] = ev
        payload = (json.dumps({"command": command, "request_id": rid}) + "\n").encode()
        try:
            if IS_WINDOWS:
                self._conn.write(payload)
                self._conn.flush()
            else:
                self._conn.sendall(payload)
        except OSError:
            with self._lock:
                self._pending.pop(rid, None)
                self._results.pop(rid, None)
            return None
        ev.wait(timeout)
        # Pop pending first: once it's gone the reader can no longer insert
        # a result for this rid, so popping results right after can't leak.
        with self._lock:
            self._pending.pop(rid, None)
            result = self._results.pop(rid, None)
        return result

    # ── Public API ───────────────────────────────────────────────────────

    def _ensure_alive(self) -> bool:
        """Restart mpv if the process or IPC connection died.

        Returns True when mpv is (or has just become) usable.
        """
        if self.is_alive() and self._running:
            return True
        with self._start_lock:
            # Double-check after acquiring the lock
            if self.is_alive() and self._running:
                return True
            self.quit()   # clean up any zombie state
            return self.start()

    def play(self, url: str, on_status: Callable[[str, str], None] | None = None) -> None:
        """
        Play a URL: local file, internet radio stream, or YouTube live.

        For YouTube URLs, resolves the HLS manifest with yt-dlp first
        (avoids mpv's ytdl_hook I/O errors with live segments).
        """
        if not url:
            return
        # Local path (no URL scheme): must exist AND have an allowed extension.
        # Without the exists() requirement a typo'd path used to reach mpv
        # and fail with an opaque error.
        if "://" not in url:
            p = Path(url)
            if not p.exists():
                if on_status:
                    on_status("File not found", "error")
                return
            if p.suffix.lower() not in ALLOWED_LOCAL_EXTS:
                if on_status:
                    on_status(f"Unsupported format: {p.suffix or '(none)'}", "error")
                return
        # Ensure mpv is alive before sending commands
        if not self._ensure_alive():
            if on_status:
                on_status("mpv is not running", "error")
            return
        # Direct play for local files and direct stream URLs
        if "youtube.com" not in url and "youtu.be" not in url:
            self._send(["loadfile", url, "replace"])
            return

        # YouTube: resolve in daemon thread
        def _resolve_and_play() -> None:
            if on_status:
                on_status("Resolving stream...", "muted")
            try:
                result = subprocess.run(
                    ["yt-dlp", "-g", "-f", "ba/91/worst", "--no-warnings", url],
                    capture_output=True, text=True, timeout=20,
                )
                lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
                real_url = lines[-1] if lines else ""
                if not real_url.startswith("http"):
                    if on_status:
                        on_status("Could not resolve stream", "error")
                    return
                # mpv may have died while yt-dlp was resolving
                if not self._ensure_alive():
                    if on_status:
                        on_status("mpv is not running", "error")
                    return
                self._send(["loadfile", real_url, "replace"])
                if on_status:
                    on_status("", "muted")
            except subprocess.TimeoutExpired:
                if on_status:
                    on_status("Timeout resolving stream", "error")
            except FileNotFoundError:
                if on_status:
                    on_status("yt-dlp not installed", "error")
            except Exception as e:
                if on_status:
                    on_status(f"Error: {str(e)[:60]}", "error")

        threading.Thread(target=_resolve_and_play, daemon=True, name="yt-resolve").start()

    def pause(self) -> None:
        self._send(["cycle", "pause"])

    def stop(self) -> None:
        self._send(["stop"])

    def set_volume(self, volume: int) -> None:
        self._send(["set_property", "volume", max(0, min(100, volume))])

    def get_paused(self) -> bool:
        return bool(self._send(["get_property", "pause"]))

    def get_time_pos(self) -> float:
        result = self._send(["get_property", "time-pos"])
        return float(result) if isinstance(result, (int, float)) else 0.0

    def get_duration(self) -> float:
        result = self._send(["get_property", "duration"])
        return float(result) if isinstance(result, (int, float)) else 0.0

    def get_media_title(self) -> str:
        result = self._send(["get_property", "media-title"])
        return str(result) if result else ""

    # Backward compatibility alias
    @property
    def socket_path(self) -> str:
        return self._ipc_path
