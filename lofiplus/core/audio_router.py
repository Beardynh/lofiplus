"""
Audio isolation router (Linux / PipeWire-Pulse only).

Creates a dedicated null sink for lofiplus so the spectrum visualizer only
ever sees OUR audio, never system notifications or other apps:

    mpv ──ao=pulse──▶ [lofiplus_<pid> null sink] ──module-loopback──▶ real sink
                              │
                              └── lofiplus_<pid>.monitor ──▶ CAVA / loopback FFT

On any failure (no pactl, module load error, non-Linux OS) setup() returns
None and the app falls back to the previous behavior (global monitor).

All pactl calls use argument lists (never shell=True) with 3 s timeouts.
"""

from __future__ import annotations

import os
import subprocess
import sys

SINK_PREFIX = "lofiplus_"
_LOOPBACK_LATENCY_MS = 60


def _pactl(*args: str, timeout: float = 3.0) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["pactl", *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


class AudioRouter:
    """Manages the per-session null sink + loopback pair."""

    def __init__(self) -> None:
        self._sink_name = f"{SINK_PREFIX}{os.getpid()}"
        self._null_module_id: str | None = None
        self._loop_module_id: str | None = None

    @property
    def sink_name(self) -> str:
        return self._sink_name

    @property
    def monitor_name(self) -> str:
        return f"{self._sink_name}.monitor"

    # ── Setup ───────────────────────────────────────────────────────────

    def setup(self) -> str | None:
        """Create the isolated sink. Returns its name, or None on failure."""
        if not sys.platform.startswith("linux"):
            return None

        self._cleanup_orphans()

        # 1) Null sink that only lofiplus' mpv will write to
        res = _pactl(
            "load-module", "module-null-sink",
            f"sink_name={self._sink_name}",
            "sink_properties=device.description=lofiplus",
        )
        if res is None or res.returncode != 0 or not res.stdout.strip().isdigit():
            return None
        self._null_module_id = res.stdout.strip()

        # 2) Loopback so the user still hears the audio on the real output
        res = _pactl(
            "load-module", "module-loopback",
            f"source={self.monitor_name}",
            "sink=@DEFAULT_SINK@",
            f"latency_msec={_LOOPBACK_LATENCY_MS}",
        )
        if res is None or res.returncode != 0 or not res.stdout.strip().isdigit():
            # Roll back the null sink — never leave half a route behind
            self.teardown()
            return None
        self._loop_module_id = res.stdout.strip()

        return self._sink_name

    # ── Teardown ────────────────────────────────────────────────────────

    def teardown(self) -> None:
        """Unload our modules (loopback first). Tolerant to every failure."""
        if self._loop_module_id is not None:
            _pactl("unload-module", self._loop_module_id)
            self._loop_module_id = None
        if self._null_module_id is not None:
            _pactl("unload-module", self._null_module_id)
            self._null_module_id = None

    # ── Orphan cleanup ──────────────────────────────────────────────────

    def _cleanup_orphans(self) -> None:
        """Unload lofiplus_* modules left behind by crashed sessions.

        A killed lofiplus can't run teardown(); its null-sink/loopback pair
        survives in the PipeWire session and would accumulate forever.
        """
        res = _pactl("list", "short", "modules")
        if res is None or res.returncode != 0:
            return
        for line in res.stdout.splitlines():
            # Format: <id>\t<module-name>\t<args>
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            module_id, module_name, args = parts[0], parts[1], parts[2]
            is_ours = (
                (module_name == "module-null-sink" and f"sink_name={SINK_PREFIX}" in args)
                or (module_name == "module-loopback" and f"source={SINK_PREFIX}" in args)
            )
            if is_ours and module_id.isdigit():
                _pactl("unload-module", module_id)
