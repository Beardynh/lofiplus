"""
GitHub Releases-based auto-updater.

- `latest_version()` queries https://api.github.com/repos/Beardynh/lofiplus/releases/latest
- Caches the result for 1 hour in ~/.cache/lofiplus/release.json
- `perform_update()` runs `git pull --ff-only` in the install dir + pip install -e .

Designed to fail silently without breaking the app — no network = just continue.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

from lofiplus import __api__, __repo__, __version__

CACHE_DIR  = Path.home() / ".cache" / "lofiplus"
CACHE_FILE = CACHE_DIR / "release.json"
CACHE_TTL  = 3600  # 1 hour

# Accepted forms of the official remote — perform_update() refuses to pull
# from anything else (defends against a swapped remote in the install dir).
_REPO_HTTPS = __repo__.rstrip("/")
_REPO_PATH  = _REPO_HTTPS.split("github.com/", 1)[-1]
_OFFICIAL_REMOTES = {
    _REPO_HTTPS,
    _REPO_HTTPS + ".git",
    f"git@github.com:{_REPO_PATH}",
    f"git@github.com:{_REPO_PATH}.git",
    f"ssh://git@github.com/{_REPO_PATH}.git",
}


class ReleaseInfo(NamedTuple):
    tag: str         # e.g. "v0.2.0"
    version: str     # e.g. "0.2.0" (tag with leading 'v' stripped)
    body: str        # release notes (markdown)
    html_url: str    # browser URL


# ── Version comparison ──────────────────────────────────────────────────────

def _parse_semver(s: str) -> tuple[int, int, int]:
    """Parse '1.2.3', 'v1.2.3' or 'v1.2.3-beta+meta' → (1, 2, 3).

    Pre-release/build suffixes are dropped so 'v1.0.0-beta' compares as
    1.0.0 instead of mis-parsing. Missing parts default to 0.
    """
    s = s.lstrip("v").strip().split("-")[0].split("+")[0]
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", s)
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0))


def is_newer(remote: str, current: str) -> bool:
    return _parse_semver(remote) > _parse_semver(current)


# ── Cache ───────────────────────────────────────────────────────────────────

def _load_cache() -> ReleaseInfo | None:
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    # The cache file is plain local data — validate every field's type
    # before trusting it (a corrupted/tampered file must not crash us
    # or smuggle non-string content into the UI).
    if not isinstance(data, dict):
        return None
    tag     = data.get("tag")
    version = data.get("version")
    body    = data.get("body", "")
    url     = data.get("html_url", "")
    checked = data.get("checked_at", 0)
    if not (
        isinstance(tag, str) and tag
        and isinstance(version, str)
        and isinstance(body, str)
        and isinstance(url, str)
        and isinstance(checked, (int, float))
    ):
        return None
    if time.time() - checked > CACHE_TTL:
        return None
    return ReleaseInfo(tag=tag, version=version, body=body, html_url=url)


def _save_cache(info: ReleaseInfo) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({
            "checked_at": time.time(),
            "tag":        info.tag,
            "version":    info.version,
            "body":       info.body,
            "html_url":   info.html_url,
        }))
    except OSError:
        pass


# ── GitHub API ──────────────────────────────────────────────────────────────

def latest_version(force: bool = False) -> ReleaseInfo | None:
    """
    Fetch the latest GitHub release. Returns None if offline or no releases.
    Result is cached for CACHE_TTL seconds.
    """
    if not force:
        cached = _load_cache()
        if cached is not None:
            return cached

    url = f"{__api__}/releases/latest"
    try:
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "lofiplus"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None

    tag = str(data.get("tag_name", "")).strip()
    if not tag:
        return None
    info = ReleaseInfo(
        tag=tag,
        version=tag.lstrip("v"),
        body=str(data.get("body", "")),
        html_url=str(data.get("html_url", "")),
    )
    _save_cache(info)
    return info


# ── CLI helpers ─────────────────────────────────────────────────────────────

def check_update(print_only: bool = True) -> bool:
    """Return True if newer version available. Prints status if print_only."""
    info = latest_version(force=True)
    if info is None:
        if print_only:
            print("⚠  Could not reach GitHub (offline?)", file=sys.stderr)
        return False
    if is_newer(info.version, __version__):
        if print_only:
            print(f"✓ Update available: v{info.version} (you have v{__version__})")
            print(f"  Release notes: {info.html_url}")
            print(f"  Run: lofiplus -a")
        return True
    if print_only:
        print(f"✓ You're up to date (v{__version__})")
    return False


def _find_install_dir() -> Path | None:
    """Locate the install directory (~/.local/share/lofiplus by default)."""
    # 1) Env var override
    env = os.environ.get("LOFIPLUS_HOME")
    if env:
        p = Path(env)
        if p.exists():
            return p
    # 2) Detect from the current package location
    here = Path(__file__).resolve().parent.parent.parent  # core/updater.py → core/ → lofiplus/ → repo/
    if (here / ".git").exists() or (here / "pyproject.toml").exists():
        return here
    # 3) Default install location
    default = Path.home() / ".local" / "share" / "lofiplus"
    if default.exists():
        return default
    return None


def perform_update() -> bool:
    """
    Pull the latest version using git + reinstall in the venv.
    Returns True if updated successfully (or already up to date).
    """
    info = latest_version(force=True)
    if info is None:
        print("⚠  Cannot check for updates (offline)", file=sys.stderr)
        return False
    if not is_newer(info.version, __version__):
        print(f"✓ Already up to date (v{__version__})")
        return True

    install_dir = _find_install_dir()
    if install_dir is None:
        print("✗ Could not locate install directory", file=sys.stderr)
        print(f"  Manually clone: git clone {_REPO_HTTPS}.git", file=sys.stderr)
        return False

    # Re-check existence: _find_install_dir() may rely on LOFIPLUS_HOME and
    # the directory can disappear between the check and the git operations.
    if not install_dir.exists() or not (install_dir / ".git").exists():
        print("✗ Install directory is not a git clone — cannot auto-update", file=sys.stderr)
        print(f"  Re-install with: git clone {_REPO_HTTPS}.git {install_dir}", file=sys.stderr)
        return False

    # Only ever pull from the official repository — a swapped remote in the
    # install dir must not become arbitrary code execution via pip install.
    try:
        remote = subprocess.run(
            ["git", "-C", str(install_dir), "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        remote = ""
    if remote.rstrip("/") not in _OFFICIAL_REMOTES:
        print(f"✗ Unexpected git remote: {remote!r}", file=sys.stderr)
        print(f"  Expected {_REPO_HTTPS} — refusing to update", file=sys.stderr)
        return False

    print(f"⇣ Updating lofiplus in {install_dir}...")
    try:
        subprocess.run(
            ["git", "-C", str(install_dir), "pull", "--ff-only"],
            check=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("✗ git pull failed", file=sys.stderr)
        return False

    # Reinstall in the venv
    venv_python = install_dir / ".venv" / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")
    if venv_python.exists():
        try:
            subprocess.run(
                [str(venv_python), "-m", "pip", "install", "--quiet", "-e", str(install_dir)],
                check=True,
            )
        except subprocess.CalledProcessError:
            print("⚠ pip install failed (the new code may need manual reinstall)", file=sys.stderr)

    # Invalidate cache so next /check sees the new version
    CACHE_FILE.unlink(missing_ok=True)

    print(f"✓ Updated to v{info.version}")
    return True
