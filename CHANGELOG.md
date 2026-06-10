# Changelog

All notable changes to lofiplus will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-06-07

### Security
- `install.sh`: removed `rsync --delete` and added install-path validation —
  a misconfigured `LOFIPLUS_HOME` could previously wipe user data
- `install.ps1`: `robocopy /MIR` → `/E` (no mirror-delete), exit-code check,
  removed `Invoke-Expression`
- Updater: `lofiplus -a` now refuses to `git pull` from any remote other than
  the official repository, re-validates the install dir, and type-checks the
  release cache before trusting it

### Fixed
- Race condition in the progress bar poller (one persistent thread instead of
  spawning a thread every 500 ms)
- Slow memory leak in the mpv IPC client when a request timed out just as its
  response arrived (orphaned `_results` entries)
- Command palette actions now run via Textual's `run_worker` (no more
  `asyncio.create_task` from a sync callback)
- Downloader thread now shuts down gracefully on exit (sentinel-based stop)
- Playing a non-existent local path now reports "File not found" instead of
  silently failing inside mpv
- Config writer escapes newlines/control characters — YouTube titles with
  exotic characters no longer corrupt `config.toml`
- Versioning normalized to semver (`1.01` → `1.0.1`)

### Added
- Now Playing: the title bar shows the actual track playing on the stream
  (icecast/YouTube metadata via mpv `media-title`)
- Auto-reconnect for dropped live streams with backoff (3 attempts)
- In-list search: press `b` and type to filter stations and local library
- `install.sh` now checks for `cava` (optional) and explains the fallback

### Removed
- Unused dependencies `scipy` and `pyfiglet`

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
