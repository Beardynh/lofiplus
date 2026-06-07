"""
Cross-platform audio loopback capture for the spectrum visualizer.

- Linux:   PipeWire/PulseAudio monitor source via `pactl list sources`
- Windows: WASAPI loopback (sounddevice picks up any output device's loopback)
- macOS:   Requires a virtual loopback driver (BlackHole, Loopback.app);
           if none is found, AudioCapture.start() returns False and
           the app falls back to a synthetic spectrum.

Memory management:
- deque(maxlen=4): discards old frames automatically, never grows
- Hann window pre-allocated in FFTProcessor.__init__
- threading.Lock held only for microseconds per operation
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from collections import deque

import numpy as np

from lofiplus.core.fft_processor import BANDS, BLOCK_SIZE, SAMPLE_RATE, FFTProcessor

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS   = sys.platform == "darwin"
IS_LINUX   = sys.platform.startswith("linux")

# Max frames in the band buffer (≈267 ms at 15 FPS)
_BUFFER_MAXLEN = 4


def find_pipewire_monitor() -> str | None:
    """Linux only: detect the active PipeWire/PulseAudio monitor source."""
    if not IS_LINUX:
        return None
    try:
        result = subprocess.run(
            ["pactl", "list", "sources"],
            capture_output=True, text=True, timeout=3,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    names  = re.findall(r"Name:\s+([\w.\-]+)", result.stdout)
    states = re.findall(r"State:\s+(\w+)", result.stdout)
    monitors = [(n, s) for n, s in zip(names, states) if n.endswith(".monitor")]
    if not monitors:
        return None
    for name, state in monitors:
        if state == "RUNNING":
            return name
    return monitors[0][0]


def find_wasapi_loopback_device():
    """Windows only: find a WASAPI loopback device for the default output."""
    try:
        import sounddevice as sd  # type: ignore
    except ImportError:
        return None
    try:
        # sounddevice exposes WASAPI loopback via hostapi 'Windows WASAPI'
        # and devices flagged with name containing '[Loopback]'
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        wasapi_idx = next(
            (i for i, h in enumerate(hostapis) if "WASAPI" in h.get("name", "")),
            None,
        )
        if wasapi_idx is None:
            return None
        # Prefer loopback-flagged devices
        for i, d in enumerate(devices):
            if d.get("hostapi") == wasapi_idx and "[Loopback]" in d.get("name", ""):
                return i
        # Fallback: default output device with WASAPI extra settings
        default_out = sd.default.device[1] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
        return default_out
    except Exception:
        return None


def find_macos_loopback_device():
    """macOS only: look for BlackHole or similar virtual loopback drivers."""
    try:
        import sounddevice as sd  # type: ignore
    except ImportError:
        return None
    try:
        for i, d in enumerate(sd.query_devices()):
            name = d.get("name", "").lower()
            if any(k in name for k in ("blackhole", "loopback", "soundflower")):
                return i
    except Exception:
        pass
    return None


class AudioCapture:
    """Loopback capture producing real-time FFT bands."""

    def __init__(self) -> None:
        self._processor = FFTProcessor()
        self._buf: deque[list[float]] = deque(maxlen=_BUFFER_MAXLEN)
        self._lock = threading.Lock()
        self._stream = None
        self._device = None

    def start(self) -> bool:
        """Detect platform-appropriate loopback and start the input stream."""
        try:
            import sounddevice as sd  # type: ignore
        except ImportError:
            return False

        stream_kwargs: dict = dict(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            channels=1,
            dtype="float32",
            callback=self._audio_callback,
        )

        if IS_LINUX:
            self._device = find_pipewire_monitor()
            if self._device is None:
                return False
            stream_kwargs["device"] = self._device

        elif IS_WINDOWS:
            self._device = find_wasapi_loopback_device()
            if self._device is None:
                return False
            stream_kwargs["device"] = self._device
            # Enable loopback via WASAPI extra_settings
            try:
                stream_kwargs["extra_settings"] = sd.WasapiSettings(loopback=True)
            except Exception:
                pass

        elif IS_MACOS:
            self._device = find_macos_loopback_device()
            if self._device is None:
                return False  # No virtual loopback installed → fallback to synthetic
            stream_kwargs["device"] = self._device

        else:
            return False

        try:
            self._stream = sd.InputStream(**stream_kwargs)
            self._stream.start()
            return True
        except Exception:
            self._stream = None
            return False

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        mono = indata[:, 0]
        bands = self._processor.compute(mono)
        with self._lock:
            self._buf.append(bands)

    def get_bands(self) -> list[float]:
        with self._lock:
            return list(self._buf[-1]) if self._buf else [0.0] * BANDS

    def reset(self) -> None:
        with self._lock:
            self._buf.clear()
        self._processor.reset()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.reset()
