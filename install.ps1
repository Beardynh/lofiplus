# lofiplus installer — Windows (PowerShell)
# Run from PowerShell:    .\install.ps1
#
# Installs to:
#   %LOCALAPPDATA%\lofiplus\         (code + venv)
#   %LOCALAPPDATA%\lofiplus\bin\     (launcher, added to PATH)

$ErrorActionPreference = "Stop"

# ─── Colors ──────────────────────────────────────────────────────────────────
function Write-OK    { param($msg) Write-Host "  " -NoNewline; Write-Host "✓" -ForegroundColor Green -NoNewline; Write-Host " $msg" }
function Write-Warn  { param($msg) Write-Host "  " -NoNewline; Write-Host "!" -ForegroundColor Yellow -NoNewline; Write-Host " $msg" }
function Write-Err   { param($msg) Write-Host "  " -NoNewline; Write-Host "✗" -ForegroundColor Red -NoNewline; Write-Host " $msg" }
function Write-Hdr   { param($msg) Write-Host ""; Write-Host $msg -ForegroundColor DarkYellow }

# ─── Paths ───────────────────────────────────────────────────────────────────
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDir = if ($env:LOFIPLUS_HOME) { $env:LOFIPLUS_HOME } else { Join-Path $env:LOCALAPPDATA "lofiplus" }
$VenvDir    = Join-Path $InstallDir ".venv"
$BinDir     = Join-Path $InstallDir "bin"
$Launcher   = Join-Path $BinDir "lofiplus.cmd"

# ─── Safety: refuse dangerous install targets ────────────────────────────────
# $InstallDir is user-controllable via LOFIPLUS_HOME; never point file
# operations at a directory that could hold unrelated user data.
$normalizedDir = $InstallDir.TrimEnd('\', '/')
if (-not $normalizedDir.ToLower().EndsWith("lofiplus")) {
    Write-Err "LOFIPLUS_HOME must end in 'lofiplus' (got: $InstallDir)"
    exit 1
}
if ($normalizedDir -eq $env:USERPROFILE -or $normalizedDir.Length -le 3) {
    Write-Err "Refusing to install into $InstallDir"
    exit 1
}

# ─── Banner ──────────────────────────────────────────────────────────────────
@'

    __        ____         __
   / /  ___  / __/_ ____  / /_ _____
  / /__/ _ \/ _// /(_-< _/ // // (_-<
 /____/\___/_/ /_(_)__/ .__/_/\_,_//___/
                     /_/

'@ | Write-Host

Write-Host "  Lo-Fi music player for your terminal"   -ForegroundColor DarkGray
Write-Host "  github.com/Beardynh/lofiplus`n"          -ForegroundColor DarkGray

# ─── 1. Check Python ─────────────────────────────────────────────────────────
Write-Hdr "1/6  Checking Python (>=3.11)"

$PythonExe  = $null
$PythonArgs = @()
$pyProbe = "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}'); sys.exit(0 if sys.version_info >= (3,11) else 1)"
foreach ($cand in @(
    @{ exe = "py";      args = @("-3.13") },
    @{ exe = "py";      args = @("-3.12") },
    @{ exe = "py";      args = @("-3.11") },
    @{ exe = "python";  args = @() },
    @{ exe = "python3"; args = @() }
)) {
    try {
        $verCheck = & $cand.exe @($cand.args) -c $pyProbe 2>$null
        if ($LASTEXITCODE -eq 0) {
            $PythonExe  = $cand.exe
            $PythonArgs = $cand.args
            Write-OK "Found $($cand.exe) $($cand.args -join ' ') (Python $verCheck)"
            break
        }
    } catch { }
}

if (-not $PythonExe) {
    Write-Err "Python 3.11+ not found"
    Write-Host "    Install from https://python.org or run: " -NoNewline
    Write-Host "winget install Python.Python.3.12" -ForegroundColor White
    exit 1
}

# ─── 2. Check system dependencies ────────────────────────────────────────────
Write-Hdr "2/6  Checking system dependencies"

$Missing = @()
foreach ($cmd in @("mpv", "yt-dlp", "ffmpeg")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        Write-OK $cmd
    } else {
        Write-Warn "$cmd not found"
        $Missing += $cmd
    }
}

if ($Missing.Count -gt 0) {
    Write-Host ""
    Write-Host "    Install missing tools with:"
    foreach ($pkg in $Missing) {
        Write-Host "      winget install $pkg" -ForegroundColor White
    }
    Write-Host ""
    $answer = Read-Host "    Continue anyway? [y/N]"
    if ($answer -notmatch '^[Yy]$') { exit 1 }
}

# ─── 3. Copy code ────────────────────────────────────────────────────────────
Write-Hdr "3/6  Installing to $InstallDir"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $BinDir     | Out-Null

if ($ScriptDir -ne $InstallDir) {
    # /E copies subdirectories without deleting anything in the destination
    # (never /MIR: $InstallDir is user-configurable and mirroring deletes)
    robocopy $ScriptDir $InstallDir /E /XD .venv __pycache__ .git build dist *.egg-info /XF *.pyc /NFL /NDL /NJH /NJS /NC /NS | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Write-Err "robocopy failed with exit code $LASTEXITCODE"
        exit 1
    }
    Write-OK "Code copied"
} else {
    Write-OK "Already in target location"
}

# ─── 4. Create venv & install ────────────────────────────────────────────────
Write-Hdr "4/6  Creating Python venv"

& $PythonExe @PythonArgs -m venv $VenvDir
if ($LASTEXITCODE -ne 0) {
    Write-Err "venv creation failed"
    exit 1
}
Write-OK "venv created at $VenvDir"

$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"
$VenvLofi   = Join-Path $VenvDir "Scripts\lofiplus.exe"

& $VenvPip install --quiet --upgrade pip
Write-OK "pip upgraded"

Write-Host "  Installing dependencies (this may take a minute)..." -ForegroundColor DarkGray
& $VenvPip install --quiet -e $InstallDir
Write-OK "lofiplus installed in editable mode"

# ─── 5. Create launcher ──────────────────────────────────────────────────────
Write-Hdr "5/6  Creating launcher"

$LauncherContent = "@echo off`r`n`"$VenvLofi`" %*`r`n"
Set-Content -Path $Launcher -Value $LauncherContent -Encoding ASCII
Write-OK "Launcher: $Launcher"

# ─── 6. PATH check ───────────────────────────────────────────────────────────
Write-Hdr "6/6  Verifying PATH"

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$NormalizedPaths = @()
if ($UserPath) {
    $NormalizedPaths = $UserPath -split ";" | ForEach-Object {
        if ($_) {
            try {
                [System.IO.Path]::GetFullPath([System.Environment]::ExpandEnvironmentVariables($_))
            } catch {
                $_
            }
        }
    }
}
$NormalizedBinDir = [System.IO.Path]::GetFullPath($BinDir)

if ($NormalizedPaths -contains $NormalizedBinDir) {
    Write-OK "$BinDir is in PATH"
} else {
    Write-Warn "$BinDir is NOT in your PATH"
    Write-Host "    Adding now..." -ForegroundColor DarkGray
    if ([string]::IsNullOrEmpty($UserPath)) {
        $NewPath = $BinDir
    } else {
        $NewPath = if ($UserPath.EndsWith(";")) { "$UserPath$BinDir" } else { "$UserPath;$BinDir" }
    }
    [Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
    Write-OK "Added to user PATH (open a new terminal for it to take effect)"
}

# ─── Done ────────────────────────────────────────────────────────────────────
$Version = & (Join-Path $VenvDir "Scripts\python.exe") -c "from lofiplus import __version__; print(__version__)" 2>$null
if (-not $Version) { $Version = "0.1.0" }

Write-Host ""
Write-Host "  ✓ lofiplus v$Version installed" -ForegroundColor Green
Write-Host ""
Write-Host "  Run " -NoNewline; Write-Host "lofiplus" -ForegroundColor DarkYellow -NoNewline; Write-Host " to start"
Write-Host "  Update with " -NoNewline; Write-Host "lofiplus -a" -ForegroundColor White
Write-Host ""
