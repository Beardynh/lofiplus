"""
Spectrum data source with three-tier fallback:

  1. CAVA (preferred) — battle-tested C visualizer, FFTW-based,
     handles native capture on all platforms. Just pipe its bars.
  2. sounddevice loopback — our own FFT, works on Linux/Windows.
  3. Synthetic — animated fake bars so the UI is never blank.

`start()` tries each tier in order and returns:
  - "cava"      if CAVA is driving the bars
  - "loopback"  if our own loopback+FFT is driving the bars
  - None        if both failed (UI falls back to synthetic)
"""

from __future__ import annotations

import math
import random
import threading
import time
from collections import deque

from lofiplus.core.audio_capture import AudioCapture
from lofiplus.core.cava_source import CavaSource
from lofiplus.core.fft_processor import BANDS


class SpectrumSource:
    def __init__(self) -> None:
        self._cava: CavaSource | None    = None
        self._capture: AudioCapture | None = None
        self._mode: str | None = None       # "cava" | "loopback" | None
        self._play  = False
        self._phases = [random.uniform(0, math.pi * 2) for _ in range(BANDS)]
        self._sm     = [0.0] * BANDS

    @property
    def mode(self) -> str | None:
        return self._mode

    def start(self, monitor: str | None = None) -> str | None:
        """Start the best available audio source.

        monitor: optional isolated monitor source (lofiplus null sink) —
        when provided, both CAVA and the loopback fallback capture from it
        so the visualizer only reacts to lofiplus' own audio.

        Returns the active mode — "cava" or "loopback" — or None when no
        real capture is available and the visualizer must use the synthetic
        generator. Callers must compare against None, not truthiness alone.
        """
        # 1) Try CAVA first
        cava = CavaSource()
        if cava.start(preferred_source=monitor):
            self._cava = cava
            self._mode = "cava"
            return "cava"

        # 2) Try our own loopback + FFT
        cap = AudioCapture()
        if cap.start(preferred_monitor=monitor):
            self._capture = cap
            self._mode = "loopback"
            return "loopback"

        # 3) Synthetic only
        self._mode = None
        return None

    def set_playing(self, playing: bool) -> None:
        self._play = playing
        if not playing:
            self._sm = [max(0.0, v * 0.85) for v in self._sm]

    def get_bands(self) -> list[float]:
        if not self._play:
            self._sm = [max(0.0, v * 0.85) for v in self._sm]
            return list(self._sm)

        # CAVA → real, smoothed, ready-to-render
        if self._cava is not None:
            return self._cava.get_bands()

        # Loopback fallback
        if self._capture is not None:
            bands = self._capture.get_bands()
            return [min(1.0, b * 1.6) for b in bands]

        # No real audio source
        return self._synth()

    def _synth(self, amp_override: float | None = None) -> list[float]:
        t   = time.time()
        amp = amp_override if amp_override is not None else (1.0 if self._play else 0.0)
        if amp <= 0.0:
            self._sm = [max(0.0, v * 0.85) for v in self._sm]
            return list(self._sm)
        out = []
        for i in range(BANDS):
            fw   = math.exp(-i / (BANDS * 0.50))
            wave = math.sin(t * (0.4 + i * 0.07) + self._phases[i]) * 0.28
            beat = abs(math.sin(t * 1.85)) ** 4 * (0.60 if i < 8 else 0.20)
            val  = fw * (0.30 + wave + beat) * amp + random.uniform(0.0, 0.03)
            s    = self._sm[i] * 0.60 + max(0.0, min(1.0, val)) * 0.40
            out.append(s)
        self._sm = out
        return list(out)

    def stop(self) -> None:
        if self._cava is not None:
            self._cava.stop()
            self._cava = None
        if self._capture is not None:
            self._capture.stop()
            self._capture = None
        self._mode = None
