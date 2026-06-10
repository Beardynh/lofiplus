"""
Station management — built-in Lo-Fi stations + local library.

Local library scan uses mtime caching to avoid filesystem walks on every
UI refresh.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from lofiplus.core.mpv_controller import ALLOWED_LOCAL_EXTS

MUSIC_DIR = Path.home() / ".lofiplusmusic"


# Curated, verified-alive YouTube live streams (rotated periodically).
# Use channel handle URLs would be ideal but mpv expects single videos;
# these IDs are the long-running 24/7 streams as of project birth.
BUILTIN_STATIONS: list[dict[str, str]] = [
    {"name": "Lofi Girl — beats to relax/study", "url": "https://www.youtube.com/watch?v=X4VbdwhkE10", "tag": "live"},
    {"name": "Lofi Girl — synth ambient",        "url": "https://www.youtube.com/watch?v=GSfT7H87zq4", "tag": "live"},
    {"name": "Lofi Girl — sad lofi / rainy",     "url": "https://www.youtube.com/watch?v=CwPCy1GLS38", "tag": "live"},
    {"name": "Chillhop — jazzy & lofi",          "url": "https://www.youtube.com/watch?v=5yx6BWlEVcY", "tag": "live"},
    {"name": "Chillhop — late night vibes",      "url": "https://www.youtube.com/watch?v=i6WzngxTnBA", "tag": "live"},
    {"name": "Radio Swiss Jazz",                 "url": "http://stream.srg-ssr.ch/m/rsj/mp3_128",      "tag": "radio"},
    {"name": "Smooth Jazz Florida",              "url": "http://smoothjazz.cdnstream1.com/2585_128.mp3","tag": "radio"},
]


@dataclass
class Track:
    name: str
    url: str
    tag: str = ""
    is_local: bool = False
    is_favorite: bool = False


class StationsConfig:
    """Built-in + custom + local-library track aggregator."""

    def __init__(self, custom_stations: list[dict] | None = None) -> None:
        self._custom = custom_stations or []
        self._local_cache: list[Track] = []
        self._last_mtime: float = 0.0

    def builtin_stations(self) -> list[Track]:
        return [Track(name=s["name"], url=s["url"], tag=s.get("tag", "")) for s in BUILTIN_STATIONS]

    def custom_stations(self) -> list[Track]:
        from urllib.parse import urlparse

        out = []
        for s in self._custom:
            if not (isinstance(s, dict) and isinstance(s.get("name"), str) and isinstance(s.get("url"), str)):
                continue
            name = s["name"].strip()
            url  = s["url"].strip()
            if not name or not url:
                continue
            # Custom stations come from a user-editable config file —
            # only accept well-formed http(s) URLs.
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                continue
            out.append(Track(name=name, url=url, tag=str(s.get("tag", "custom"))))
        return out

    def scan_local(self) -> list[Track]:
        if not MUSIC_DIR.exists():
            return []
        try:
            current_mtime = os.stat(MUSIC_DIR).st_mtime
        except OSError:
            return []

        if current_mtime == self._last_mtime:
            return self._local_cache

        tracks: list[Track] = []
        try:
            for entry in sorted(MUSIC_DIR.iterdir()):
                if entry.is_file() and entry.suffix.lower() in ALLOWED_LOCAL_EXTS:
                    tracks.append(Track(name=entry.stem, url=str(entry), tag="local", is_local=True))
        except OSError:
            pass

        self._local_cache = tracks
        self._last_mtime = current_mtime
        return tracks

    def all_tracks(self) -> list[Track]:
        return self.builtin_stations() + self.custom_stations() + self.scan_local()
