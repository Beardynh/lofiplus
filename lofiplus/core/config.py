"""
Persistent user configuration in ~/.config/lofiplus/config.toml

Uses tomllib (stdlib, Python 3.11+) for reading. Writing uses a simple
hand-rolled serializer (no extra dependency) — the config schema is flat
enough that we don't need a full TOML writer.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib  # type: ignore[import-not-found]
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found, no-redef]


CONFIG_DIR  = Path.home() / ".config" / "lofiplus"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass
class Config:
    # [player]
    volume: int = 70
    last_played: str = ""

    # [appearance]
    theme: str = "dark"
    visualizer: str = "aurora"  # "aurora" | "bars"

    # [update]
    auto_check: bool = True
    check_interval_hours: int = 24

    # [favorites] — list of track names marked as favorites
    favorites: list[str] = field(default_factory=list)

    # [stations.custom] — user-defined stations
    custom_stations: list[dict[str, str]] = field(default_factory=list)


# ── Load ────────────────────────────────────────────────────────────────────

def load() -> Config:
    if not CONFIG_FILE.exists():
        return Config()
    try:
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return Config()

    player     = data.get("player", {})
    appearance = data.get("appearance", {})
    update     = data.get("update", {})
    favorites  = data.get("favorites", {})
    stations   = data.get("stations", {})

    visualizer = str(appearance.get("visualizer", "aurora"))
    if visualizer not in ("aurora", "bars"):
        visualizer = "aurora"

    return Config(
        volume               = int(player.get("volume", 70)),
        last_played          = str(player.get("last_played", "")),
        theme                = str(appearance.get("theme", "dark")),
        visualizer           = visualizer,
        auto_check           = bool(update.get("auto_check", True)),
        check_interval_hours = int(update.get("check_interval_hours", 24)),
        favorites            = list(favorites.get("tracks", [])),
        custom_stations      = list(stations.get("custom", [])),
    )


# ── Save (simple writer, no extra dep) ──────────────────────────────────────

def _esc(s: str) -> str:
    """Escape a string for a TOML basic string.

    Real-world YouTube titles contain quotes, backslashes and even newlines —
    all of which would corrupt the file (and lose the user's favorites) if
    written raw.
    """
    out = s.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    # Drop any remaining control characters TOML forbids
    return "".join(ch for ch in out if ch >= " " or ch in ("\\",))


def save(cfg: Config) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    lines: list[str] = []
    lines.append("# lofiplus config — edit freely, app reloads on next start")
    lines.append("")
    lines.append("[player]")
    lines.append(f"volume = {cfg.volume}")
    lines.append(f'last_played = "{_esc(cfg.last_played)}"')
    lines.append("")
    lines.append("[appearance]")
    lines.append(f'theme = "{_esc(cfg.theme)}"')
    lines.append(f'visualizer = "{_esc(cfg.visualizer)}"')
    lines.append("")
    lines.append("[update]")
    lines.append(f"auto_check = {'true' if cfg.auto_check else 'false'}")
    lines.append(f"check_interval_hours = {cfg.check_interval_hours}")
    lines.append("")
    lines.append("[favorites]")
    if cfg.favorites:
        favs = ", ".join(f'"{_esc(f)}"' for f in cfg.favorites)
        lines.append(f"tracks = [{favs}]")
    else:
        lines.append("tracks = []")
    lines.append("")
    lines.append("[stations]")
    if cfg.custom_stations:
        lines.append("custom = [")
        for s in cfg.custom_stations:
            name = _esc(str(s.get("name", "")))
            url  = _esc(str(s.get("url", "")))
            tag  = _esc(str(s.get("tag", "custom")))
            lines.append(f'  {{ name = "{name}", url = "{url}", tag = "{tag}" }},')
        lines.append("]")
    else:
        lines.append("custom = []")
    lines.append("")

    try:
        CONFIG_FILE.write_text("\n".join(lines))
    except OSError:
        pass
