"""
yt-dlp based audio downloader.

- Single download worker thread (queue maxsize=1, never accumulates)
- Streams directly to ~/.lofiplusmusic (no RAM buffering)
- Auto-cleans stale .part files on failure
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Callable

MUSIC_DIR = Path.home() / ".lofiplusmusic"

# (message, kind) where kind ∈ {"muted", "ok", "error"}
ProgressCallback = Callable[[str, str], None]


class Downloader:
    def __init__(self, on_progress: ProgressCallback | None = None) -> None:
        self._cb = on_progress
        self._stopping = False
        # None is the shutdown sentinel
        self._q: queue.Queue[str | None] = queue.Queue(maxsize=1)
        threading.Thread(target=self._worker, daemon=True, name="yt-dlp").start()

    def enqueue(self, url: str) -> bool:
        if self._stopping:
            return False
        try:
            self._q.put_nowait(url)
            return True
        except queue.Full:
            return False

    def stop(self) -> None:
        """Best-effort graceful shutdown: drain pending URLs, wake the worker."""
        self._stopping = True
        try:
            while True:
                self._q.get_nowait()
                self._q.task_done()
        except queue.Empty:
            pass
        try:
            self._q.put_nowait(None)
        except queue.Full:
            pass  # worker is mid-download; daemon thread dies with the process

    def _worker(self) -> None:
        while True:
            url = self._q.get()
            if url is None:
                self._q.task_done()
                break
            try:
                self._run(url)
            except Exception as e:
                if self._cb:
                    self._cb(f"Error: {str(e)[:60]}", "error")
            finally:
                self._q.task_done()

    def _run(self, url: str) -> None:
        try:
            import yt_dlp  # type: ignore
        except ImportError:
            if self._cb:
                self._cb("yt-dlp not installed", "error")
            return

        MUSIC_DIR.mkdir(parents=True, exist_ok=True)

        def hook(d: dict) -> None:
            if not self._cb:
                return
            s = d.get("status", "")
            if s == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                dl    = d.get("downloaded_bytes", 0)
                pct   = dl / total if total > 0 else 0.0
                fname = Path(d.get("filename", "")).name[:35]
                self._cb(f"Downloading {fname} ({pct:.0%})", "muted")
            elif s == "finished":
                fname = Path(d.get("filename", "")).name[:35]
                self._cb(f"Saved: {fname}", "ok")
            elif s == "error":
                self._cb("Download error", "error")
                for p in MUSIC_DIR.glob("*.part"):
                    p.unlink(missing_ok=True)

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(MUSIC_DIR / "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook],
            "keepvideo": False,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
