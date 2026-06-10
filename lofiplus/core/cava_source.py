"""
CAVA-backed spectrum source.

Spawns the `cava` binary (https://github.com/karlstav/cava) in raw output
mode and reads 16-bit unsigned integers from its stdout. Each frame is
`N_BARS × 2` bytes (uint16 little-endian), values 0–65535 representing the
height of each frequency bar.

CAVA does ALL of the hard work:
  - Native audio capture (PipeWire/Pulse/ALSA/Jack on Linux,
    CoreAudio on macOS, WASAPI on Windows)
  - FFTW-based FFT
  - Monstercat smoothing + integral filter + gravity
  - Autosens (auto-gain)
  - Frequency-to-bar mapping (logarithmic)

We just read the values and render them.
"""

from __future__ import annotations

import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from collections import deque
from pathlib import Path

N_BARS    = 32
FRAMERATE = 60
BYTES_PER_FRAME = N_BARS * 2  # uint16


def _get_cava_candidates() -> list[tuple[str, str]]:
    """Return a list of (method, source) candidate configurations for CAVA based on OS."""
    candidates = []
    if sys.platform.startswith("linux"):
        # 1. Prefer modern pipewire if it is running
        try:
            res = subprocess.run(["pactl", "info"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0 and "pipewire" in res.stdout.lower():
                candidates.append(("pipewire", "auto"))
        except Exception:
            pass

        # 2. Try pulse with default sink monitor
        try:
            res = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0 and res.stdout.strip():
                candidates.append(("pulse", f"{res.stdout.strip()}.monitor"))
        except Exception:
            pass

        # 3. Try pulse with any running monitor source
        try:
            import re
            res = subprocess.run(["pactl", "list", "sources"], capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                names = re.findall(r"Name:\s+([\w.\-]+)", res.stdout)
                states = re.findall(r"State:\s+(\w+)", res.stdout)
                monitors = [n for n, s in zip(names, states) if n.endswith(".monitor") and s == "RUNNING"]
                for m in monitors:
                    candidates.append(("pulse", m))
                all_monitors = [n for n in names if n.endswith(".monitor")]
                for m in all_monitors:
                    if ("pulse", m) not in candidates:
                        candidates.append(("pulse", m))
        except Exception:
            pass

        # 4. Fallback to pulse auto
        if ("pulse", "auto") not in candidates:
            candidates.append(("pulse", "auto"))

    elif sys.platform == "darwin":
        candidates.append(("portaudio", "auto"))
    elif sys.platform.startswith("win"):
        candidates.append(("portaudio", "auto"))
    else:
        candidates.append(("portaudio", "auto"))

    return candidates


_CAVA_CONFIG_TPL = """[general]
bars = {bars}
framerate = {framerate}
autosens = 1
sensitivity = 100

[input]
method = {method}
source = {source}

[output]
method = raw
raw_target = /dev/stdout
bit_format = 16bit
channels = mono

[smoothing]
monstercat = 1
noise_reduction = 65
"""


class CavaSource:
    """Streams spectrum band values from a `cava` subprocess."""

    def __init__(self) -> None:
        self._proc:    subprocess.Popen | None = None
        self._reader:  threading.Thread | None = None
        self._running = False
        self._config_path: Path | None = None
        self._buf: deque[list[float]] = deque(maxlen=2)
        self._lock = threading.Lock()

    @staticmethod
    def is_available() -> bool:
        return shutil.which("cava") is not None

    def start(self) -> bool:
        if not self.is_available():
            return False

        candidates = _get_cava_candidates()
        for method, source in candidates:
            config_text = _CAVA_CONFIG_TPL.format(
                bars=N_BARS,
                framerate=FRAMERATE,
                method=method,
                source=source,
            )

            # Write a temp config file (cava needs a file, not stdin)
            try:
                fd, path = tempfile.mkstemp(prefix="lofiplus_cava_", suffix=".conf")
                try:
                    os.write(fd, config_text.encode())
                finally:
                    os.close(fd)
                self._config_path = Path(path)
            except OSError:
                continue

            try:
                self._proc = subprocess.Popen(
                    ["cava", "-p", str(self._config_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
            except (FileNotFoundError, OSError):
                self._cleanup_config()
                continue

            # Make sure cava actually started — give it a moment to see if it exits
            import time
            time.sleep(0.08)
            if self._proc.poll() is None:
                # Started successfully!
                self._running = True
                self._reader = threading.Thread(
                    target=self._read_loop, daemon=True, name="cava-reader"
                )
                self._reader.start()
                return True
            else:
                self._cleanup_config()

        return False

    def _read_loop(self) -> None:
        """Read frames from cava's stdout using an accumulating buffer.

        CAVA writes raw uint16 data in variable-size chunks due to pipe
        buffering, so we accumulate bytes and extract complete frames.
        """
        if self._proc is None or self._proc.stdout is None:
            return
        stdout = self._proc.stdout
        fmt = f"<{N_BARS}H"  # little-endian, N_BARS unsigned shorts
        buf = b""
        while self._running:
            try:
                chunk = stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                # Extract as many complete frames as possible
                while len(buf) >= BYTES_PER_FRAME:
                    frame = buf[:BYTES_PER_FRAME]
                    buf = buf[BYTES_PER_FRAME:]
                    values = struct.unpack(fmt, frame)
                    bands = [v / 65535.0 for v in values]
                    with self._lock:
                        self._buf.append(bands)
            except (OSError, struct.error):
                break

    def get_bands(self) -> list[float]:
        with self._lock:
            return list(self._buf[-1]) if self._buf else [0.0] * N_BARS

    def stop(self) -> None:
        self._running = False
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
        self._cleanup_config()

    def _cleanup_config(self) -> None:
        if self._config_path is not None:
            # Belt-and-braces: only ever delete a file we created ourselves
            if self._config_path.name.startswith("lofiplus_cava_"):
                try:
                    self._config_path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._config_path = None
