#!/usr/bin/env bash
# lofiplus installer — Linux & macOS
# Idempotent: safe to run multiple times.
#
# Installs lofiplus to:
#   ~/.local/share/lofiplus/      (code + venv)
#   ~/.local/bin/lofiplus         (launcher)

set -euo pipefail

# ─── Colors ──────────────────────────────────────────────────────────────────
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
    BOLD="$(tput bold)"
    DIM="$(tput dim)"
    RED="$(tput setaf 1)"
    GREEN="$(tput setaf 2)"
    YELLOW="$(tput setaf 3)"
    BLUE="$(tput setaf 4)"
    AMBER="$(tput setaf 214 2>/dev/null || tput setaf 3)"
    RESET="$(tput sgr0)"
else
    BOLD="" DIM="" RED="" GREEN="" YELLOW="" BLUE="" AMBER="" RESET=""
fi

ok()   { printf "  ${GREEN}✓${RESET} %s\n" "$*"; }
warn() { printf "  ${YELLOW}!${RESET} %s\n" "$*"; }
err()  { printf "  ${RED}✗${RESET} %s\n" "$*" >&2; }
hdr()  { printf "\n${BOLD}${AMBER}%s${RESET}\n" "$*"; }

# ─── Paths (XDG Base Directory) ──────────────────────────────────────────────
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${LOFIPLUS_HOME:-$HOME/.local/share/lofiplus}"
BIN_DIR="${LOFIPLUS_BIN:-$HOME/.local/bin}"
VENV_DIR="$INSTALL_DIR/.venv"
LAUNCHER="$BIN_DIR/lofiplus"

# ─── Safety: refuse dangerous install targets ────────────────────────────────
# INSTALL_DIR is user-controllable via LOFIPLUS_HOME; never point file
# operations at a directory that could hold unrelated user data.
case "$INSTALL_DIR" in
    */lofiplus) ;;
    *)
        printf "  ✗ LOFIPLUS_HOME must end in '/lofiplus' (got: %s)\n" "$INSTALL_DIR" >&2
        exit 1
        ;;
esac
if [[ "$INSTALL_DIR" == "$HOME" || "$INSTALL_DIR" == "/" ]]; then
    printf "  ✗ Refusing to install into %s\n" "$INSTALL_DIR" >&2
    exit 1
fi

OS="$(uname -s)"
case "$OS" in
    Linux*)   PLATFORM="linux"; PKG_HINT="" ;;
    Darwin*)  PLATFORM="macos"; PKG_HINT="brew install" ;;
    *)        err "Unsupported OS: $OS (this script is for Linux/macOS; use install.ps1 on Windows)"
              exit 1 ;;
esac

if [[ "$PLATFORM" == "linux" ]]; then
    if   command -v pacman  >/dev/null 2>&1; then PKG_HINT="sudo pacman -S"
    elif command -v apt-get >/dev/null 2>&1; then PKG_HINT="sudo apt install"
    elif command -v dnf     >/dev/null 2>&1; then PKG_HINT="sudo dnf install"
    elif command -v zypper  >/dev/null 2>&1; then PKG_HINT="sudo zypper install"
    else                                          PKG_HINT="<your package manager>"
    fi
fi

# ─── Banner ──────────────────────────────────────────────────────────────────
cat <<'EOF'

    __        ____         __
   / /  ___  / __/_ ____  / /_ _____
  / /__/ _ \/ _// /(_-< _/ // // (_-<
 /____/\___/_/ /_(_)__/ .__/_/\_,_//___/
                     /_/

EOF
printf "${DIM}  Lo-Fi music player for your terminal${RESET}\n"
printf "${DIM}  github.com/Beardynh/lofiplus${RESET}\n"

# ─── 1. Check Python ─────────────────────────────────────────────────────────
hdr "1/6  Checking Python (≥3.11)"

PYTHON=""
for cand in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        ver="$("$cand" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "")"
        if [[ -n "$ver" ]] && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
            PYTHON="$cand"
            ok "Found $cand (Python $ver)"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    err "Python 3.11+ not found"
    printf "    Install with: ${BOLD}%s python${RESET}\n" "$PKG_HINT"
    exit 1
fi

# ─── 2. Check system dependencies ────────────────────────────────────────────
hdr "2/6  Checking system dependencies"

declare -a MISSING=()
for cmd in mpv yt-dlp ffmpeg; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ok "$cmd"
    else
        warn "$cmd not found"
        MISSING+=("$cmd")
    fi
done

# cava is optional: without it the spectrum falls back to loopback/synthetic
if command -v cava >/dev/null 2>&1; then
    ok "cava (real-time spectrum)"
else
    warn "cava not found — spectrum will use loopback/synthetic fallback"
    printf "    Optional: ${BOLD}%s cava${RESET}\n" "$PKG_HINT"
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
    printf "\n    Install missing tools with:\n"
    printf "    ${BOLD}%s %s${RESET}\n\n" "$PKG_HINT" "${MISSING[*]}"
    printf "    Continue anyway? [y/N] "
    read -r answer || exit 1
    [[ "$answer" =~ ^[Yy]$ ]] || exit 1
fi

# ─── 3. Copy code to INSTALL_DIR ─────────────────────────────────────────────
hdr "3/6  Installing to $INSTALL_DIR"

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

if [[ "$SCRIPT_DIR" != "$INSTALL_DIR" ]]; then
    # Plain copy (no --delete: INSTALL_DIR may be user-configured; never
    # mirror-delete a directory we don't fully own)
    if command -v rsync >/dev/null 2>&1; then
        rsync -a \
            --exclude='.venv' --exclude='__pycache__' \
            --exclude='*.pyc' --exclude='.git' \
            --exclude='build' --exclude='dist' --exclude='*.egg-info' \
            "$SCRIPT_DIR/" "$INSTALL_DIR/" || { err "rsync failed"; exit 1; }
    else
        cp -R "$SCRIPT_DIR/." "$INSTALL_DIR/" || { err "copy failed"; exit 1; }
    fi
    ok "Code copied"
else
    ok "Already in target location"
fi

# ─── 4. Create venv & install ────────────────────────────────────────────────
hdr "4/6  Creating Python venv"

"$PYTHON" -m venv "$VENV_DIR"
ok "venv created at $VENV_DIR"

"$VENV_DIR/bin/pip" install --quiet --upgrade pip
ok "pip upgraded"

printf "  ${DIM}Installing dependencies (this may take a minute)...${RESET}\n"
"$VENV_DIR/bin/pip" install --quiet -e "$INSTALL_DIR"
ok "lofiplus installed in editable mode"

# ─── 5. Create launcher ──────────────────────────────────────────────────────
hdr "5/6  Creating launcher"

cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/lofiplus" "\$@"
EOF
chmod +x "$LAUNCHER"
ok "Launcher: $LAUNCHER"

# ─── 6. PATH check ───────────────────────────────────────────────────────────
hdr "6/6  Verifying PATH"

if echo "$PATH" | tr ':' '\n' | grep -Fqx "$BIN_DIR"; then
    ok "$BIN_DIR is in PATH"
else
    warn "$BIN_DIR is NOT in your PATH"
    case "${SHELL:-/bin/bash}" in
        */zsh)  RC="$HOME/.zshrc" ;;
        */bash) RC="$HOME/.bashrc" ;;
        */fish) RC="$HOME/.config/fish/config.fish" ;;
        *)      RC="$HOME/.profile" ;;
    esac
    printf "    Add this line to ${BOLD}%s${RESET}:\n" "$RC"
    if [[ "$RC" == *"fish"* ]]; then
        printf "      ${BOLD}set -gx PATH %s \$PATH${RESET}\n" "$BIN_DIR"
    else
        printf "      ${BOLD}export PATH=\"%s:\$PATH\"${RESET}\n" "$BIN_DIR"
    fi
    printf "    Then run: ${BOLD}source %s${RESET}\n\n" "$RC"
fi

# ─── Done ────────────────────────────────────────────────────────────────────
VERSION="$("$VENV_DIR/bin/python" -c 'from lofiplus import __version__; print(__version__)' 2>/dev/null || echo "0.1.0")"

printf "\n${GREEN}${BOLD}  ✓ lofiplus v%s installed${RESET}\n\n" "$VERSION"
printf "  Run ${BOLD}${AMBER}lofiplus${RESET} to start\n"
printf "  Update with ${BOLD}lofiplus -a${RESET}\n\n"
