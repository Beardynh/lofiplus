"""
Procesador FFT para el visualizador de espectro.

Recibe bloques PCM mono float32 y devuelve 32 bandas de magnitud
logarítmicamente espaciadas entre 20 Hz y 20 kHz, normalizadas a [0.0, 1.0].

Gestión de memoria:
- La ventana Hann y los bins de frecuencia se pre-asignan en __init__.
- No se crean arrays nuevos en compute(); se reutilizan los pre-asignados.
- Smoothing exponencial in-place sobre self._smoothed.
"""

from __future__ import annotations

import numpy as np

BANDS = 32
SAMPLE_RATE = 44100
BLOCK_SIZE = 2048
DB_FLOOR = -60.0          # noise floor — higher (less negative) = more sensitive
SMOOTH_ALPHA = 0.55       # frame retention; lower = snappier reaction


class FFTProcessor:
    """Calcula 32 bandas de espectro a partir de PCM mono float32."""

    def __init__(
        self,
        bands: int = BANDS,
        sample_rate: int = SAMPLE_RATE,
        block_size: int = BLOCK_SIZE,
    ) -> None:
        self._bands = bands
        self._sr = sample_rate
        self._block = block_size

        # Pre-asignación única — nunca recrear en compute()
        self._window: np.ndarray = np.hanning(block_size).astype(np.float32)
        self._fft_buf: np.ndarray = np.zeros(block_size // 2 + 1, dtype=np.float32)
        self._smoothed: np.ndarray = np.zeros(bands, dtype=np.float32)

        # Límites de bins de frecuencia logarítmicamente espaciados
        freqs = np.fft.rfftfreq(block_size, d=1.0 / sample_rate)
        log_edges = np.logspace(np.log10(20.0), np.log10(20000.0), bands + 1)
        self._bin_ranges: list[tuple[int, int]] = []
        for lo, hi in zip(log_edges[:-1], log_edges[1:]):
            idx = np.where((freqs >= lo) & (freqs < hi))[0]
            if idx.size > 0:
                self._bin_ranges.append((int(idx[0]), int(idx[-1]) + 1))
            else:
                # Banda vacía → usar bin más cercano
                closest = int(np.argmin(np.abs(freqs - (lo + hi) / 2)))
                self._bin_ranges.append((closest, closest + 1))

    def compute(self, pcm: np.ndarray) -> list[float]:
        """
        Calcula las bandas FFT de un bloque PCM mono.

        pcm: array float32 de longitud <= self._block (se trunca o rellena)
        Retorna lista de 32 floats en [0.0, 1.0].
        """
        n = min(len(pcm), self._block)
        # Aplicar ventana Hann in-place sobre una vista del bloque
        windowed = pcm[:n] * self._window[:n]

        # FFT real → magnitudes en self._fft_buf (reutilizado)
        spectrum = np.abs(np.fft.rfft(windowed, n=self._block))
        np.copyto(self._fft_buf, spectrum.astype(np.float32))

        # Mapear a 32 bandas con normalización dBFS
        for i, (lo, hi) in enumerate(self._bin_ranges):
            mag = float(np.mean(self._fft_buf[lo:hi]))
            db = 20.0 * np.log10(max(mag, 1e-9)) - DB_FLOOR  # rango 0..+80
            normalized = max(0.0, min(1.0, db / abs(DB_FLOOR)))
            # Smoothing exponencial in-place
            self._smoothed[i] = self._smoothed[i] * SMOOTH_ALPHA + normalized * (1.0 - SMOOTH_ALPHA)

        return self._smoothed.tolist()

    def reset(self) -> None:
        """Reinicia el buffer de smoothing (al parar la reproducción)."""
        self._smoothed[:] = 0.0
