# Changelog

All notable changes to lofiplus will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-06-06

### Added
- Initial release of lofiplus
- Interactive TUI built with Textual framework
- Real-time 32-band spectrum analyzer with three-tier fallback:
  1. **CAVA** (preferred) — battle-tested C visualizer, FFTW-based
  2. **sounddevice loopback** — own FFT, PipeWire/WASAPI
  3. **Synthetic** — animated fake bars so the UI is never blank
- Premium half-block spectrum visualizer (▀/▄) with 2× vertical resolution
- Smooth per-height color gradient (24-step pre-computed LUT)
- Floating peak-hold indicators with gravity decay
- Frequency-dependent temporal smoothing (heavy bass, snappy treble)
- Subtle reflection effect below the equalizer baseline
- mpv player control via Unix IPC socket (JSON protocol)
- 7 curated Lo-Fi live stations (Lofi Girl, Chillhop, Radio Swiss Jazz, etc.)
- yt-dlp integration for downloading audio (saved to `~/.lofiplusmusic/`)
- Local library scanning with format whitelist (MP3, FLAC, WAV, AAC, AIFF, MP4, MOV, WEBM)
- Keyboard-driven navigation (no mouse required)
- Smooth interpolated progress bar for local files
- Static progress indicator for live streams / radios
- Auto YouTube live URL resolution (handles HLS manifest expiry)
- Cross-platform support: Linux, macOS, Windows
- `install.sh` for Linux/macOS, `install.ps1` for Windows
- `lofiplus -v`, `lofiplus -a`, `lofiplus --check` CLI flags
- `/act` slash command in TUI for checking updates

### Memory & performance
- Strict RAM management: fixed-size buffers (~80MB total Python footprint)
- Pre-allocated numpy arrays for FFT (no per-frame allocation)
- Single-thread downloader queue (maxsize=1)
- Auto-cleanup of stale `.part` files on download failure
- Buffered CAVA pipe reader (accumulating buffer handles variable-size OS chunks)

[Unreleased]: https://github.com/Beardynh/lofiplus/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Beardynh/lofiplus/releases/tag/v0.1.0
