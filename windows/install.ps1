<#
.SYNOPSIS
    One-time setup for Chamber Scribe: Python virtual environment + deps,
    FFmpeg, and MongoDB - installing FFmpeg/MongoDB via winget if they
    aren't already on this machine.

.NOTES
    Run from the repo root:  .\windows\install.ps1
    Safe to re-run - every step checks whether it's already done first.
#>

$ErrorActionPreference = "Stop"

# This script lives in windows\ but operates on the repo root - works
# whether it's invoked as .\windows\install.ps1 from the root, or run
# directly from inside windows\.
Set-Location (Split-Path -Parent $PSScriptRoot)

function Test-CommandExists($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Write-Step($msg) {
    Write-Host ""
    Write-Host "== $msg ==" -ForegroundColor Cyan
}

# This project requires exactly Python 3.12 (not 3.11, not 3.13) - checked
# by version, not just presence, since a machine can easily have some other
# Python on PATH already. The 'py' launcher (installed alongside Python on
# Windows, including by winget's Python.Python.3.12) tracks every installed
# version separately and can select 3.12 specifically even if a different
# version is what 'python' resolves to - so it's checked first.
function Get-Python312Command {
    if (Test-CommandExists "py") {
        $v = & py -3.12 -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -eq "3 12") {
            return "py -3.12"
        }
    }
    if (Test-CommandExists "python") {
        $v = & python -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -eq "3 12") {
            return "python"
        }
    }
    return $null
}

function Invoke-Python312([string[]]$PyArgs) {
    if ($script:python312 -eq "py -3.12") {
        & py -3.12 @PyArgs
    } else {
        & python @PyArgs
    }
}

# -- 0. Sanity checks ---------------------------------------------------------
Write-Step "Checking prerequisites"

$hasWinget = Test-CommandExists "winget"
if (-not $hasWinget) {
    Write-Host "winget not found - FFmpeg/MongoDB/Python auto-install will be skipped. Install App Installer from the Microsoft Store to get winget, or install them manually (links below if needed)." -ForegroundColor Yellow
}

$python312 = Get-Python312Command
if (-not $python312) {
    Write-Host "Python 3.12 not found (this project requires exactly 3.12 - a different version already on PATH isn't enough)." -ForegroundColor Yellow

    if ($hasWinget) {
        $installPython = Read-Host "Install Python 3.12 now via winget? (y/N)"
        if ($installPython -eq "y" -or $installPython -eq "Y") {
            winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements

            # winget registers the new PATH entry in the registry, but this
            # terminal's own $env:Path was loaded at session start and won't
            # see it - reload from the registry so the new install works
            # without having to close and reopen the terminal.
            $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
            $python312 = Get-Python312Command
        } else {
            Write-Host "Skipping Python install." -ForegroundColor Yellow
        }
    }

    if (-not $python312) {
        Write-Host "Python 3.12 still not found. Install it from https://www.python.org/downloads/ (get 3.12 specifically - not a newer or older version - and check 'Add python.exe to PATH' during install), close and reopen your terminal, then re-run this script." -ForegroundColor Red
        exit 1
    }
    Write-Host "Python 3.12 is now available ($python312)." -ForegroundColor Green
}

# -- 1. Python virtual environment + dependencies -----------------------------
Write-Step "Python virtual environment"

if (Test-Path ".\venv\Scripts\python.exe") {
    $venvVersion = & .\venv\Scripts\python.exe -c "import sys; print(sys.version_info[0], sys.version_info[1])" 2>$null
    if ($venvVersion -ne "3 12") {
        Write-Host "Existing venv is not Python 3.12 (found: $venvVersion). Delete the venv folder and re-run this script to rebuild it with 3.12." -ForegroundColor Red
        exit 1
    }
    Write-Host "venv already exists (Python 3.12) - skipping creation."
} else {
    Write-Host "Creating venv with Python 3.12..."
    Invoke-Python312 @("-m", "venv", "venv")
}

Write-Step "Installing Python dependencies"
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip failed to install requirements.txt (see errors above) - stopping so the rest of the script doesn't run against a broken environment." -ForegroundColor Red
    exit 1
}

# torch isn't pinned in requirements.txt (see the comment there) - it's
# installed here instead, separately, so a stale/unavailable torch build
# can't take the other packages down with it. If an NVIDIA GPU is present,
# try CUDA-enabled builds first so Whisper actually uses the GPU (the
# difference between ~1-5 min and much longer per transcription) - see
# services/transcriber/config.py, which picks cuda/cpu automatically based
# on what torch reports as available. PyTorch's CUDA index tags change
# over time, so a few are tried, newest first, falling back to plain
# CPU-only torch if none of them work.
Write-Step "Installing PyTorch"

$torchInstalled = $false

if (Test-CommandExists "nvidia-smi") {
    Write-Host "NVIDIA GPU detected - trying CUDA-enabled torch builds..." -ForegroundColor Yellow
    foreach ($cudaTag in @("cu130", "cu128", "cu126", "cu121")) {
        Write-Host "Trying $cudaTag..."
        .\venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/$cudaTag
        if ($LASTEXITCODE -eq 0) {
            Write-Host "Installed torch (CUDA $cudaTag)." -ForegroundColor Green
            $torchInstalled = $true
            break
        }
        Write-Host "$cudaTag didn't work, trying the next one..." -ForegroundColor Yellow
    }
    if (-not $torchInstalled) {
        Write-Host "None of the CUDA builds installed - falling back to CPU-only torch. GPU acceleration won't be available; Whisper will still work, just slower." -ForegroundColor Yellow
    }
} else {
    Write-Host "No NVIDIA GPU detected (nvidia-smi not found) - installing CPU-only torch. Whisper transcription will work but be slower." -ForegroundColor Yellow
}

if (-not $torchInstalled) {
    .\venv\Scripts\python.exe -m pip install torch
    if ($LASTEXITCODE -eq 0) {
        $torchInstalled = $true
    }
}

if (-not $torchInstalled) {
    Write-Host "torch failed to install (see errors above). The app needs it to run - fix the error and re-run this script." -ForegroundColor Red
    exit 1
}

# -- 2. FFmpeg ------------------------------------------------------------------
Write-Step "FFmpeg"

if (Test-CommandExists "ffmpeg") {
    Write-Host "FFmpeg already installed - skipping." -ForegroundColor Green
} elseif ($hasWinget) {
    Write-Host "Installing FFmpeg via winget..."
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    Write-Host "FFmpeg installed. You may need to open a new terminal for PATH changes to take effect." -ForegroundColor Yellow
} else {
    Write-Host "Install FFmpeg manually: https://ffmpeg.org/download.html (make sure ffmpeg.exe ends up on PATH)." -ForegroundColor Red
}

# -- 3. MongoDB -------------------------------------------------------------------
Write-Step "MongoDB"

$mongoInstalled = (Test-CommandExists "mongod") -or (Get-Service -Name "MongoDB" -ErrorAction SilentlyContinue)

if ($mongoInstalled) {
    Write-Host "MongoDB already installed - skipping install." -ForegroundColor Green
} elseif ($hasWinget) {
    Write-Host "Installing MongoDB Community Server via winget (this registers it as a Windows service)..."
    winget install -e --id MongoDB.Server --accept-source-agreements --accept-package-agreements
} else {
    Write-Host "Install MongoDB manually: https://www.mongodb.com/try/download/community" -ForegroundColor Red
}

# Make sure the service is actually running, whether it was just installed
# or already present.
$svc = Get-Service -Name "MongoDB" -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -ne "Running") {
        Write-Host "Starting MongoDB service..."
        Start-Service MongoDB
    }
    Write-Host "MongoDB service status: $((Get-Service MongoDB).Status)" -ForegroundColor Green
} else {
    Write-Host "MongoDB service not found yet. If you just installed it, close and reopen your terminal (or restart) and re-run this script - Windows sometimes needs a fresh session to see a newly registered service." -ForegroundColor Yellow
}

# -- 4. .env ------------------------------------------------------------------------
Write-Step "Environment file"

if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env"
    Write-Host "Created .env from .env.example. Defaults already point at a local MongoDB instance (mongodb://localhost:27017) - edit .env if yours differs." -ForegroundColor Yellow
} else {
    Write-Host ".env already exists - leaving it as-is." -ForegroundColor Green
}

# -- Done -----------------------------------------------------------------------------
Write-Step "Setup complete"
Write-Host "Sanity check the database connection:  .\venv\Scripts\python.exe -m scripts.db_utils summary"
Write-Host ""

$startNow = Read-Host "Start Chamber Scribe now (pipeline + API in the background)? (y/N)"
if ($startNow -eq "y" -or $startNow -eq "Y") {
    & "$PSScriptRoot\start.ps1"
} else {
    Write-Host "Start it later with:  .\windows\start.ps1"
    Write-Host "Or run it in the foreground instead:"
    Write-Host "  Pipeline:  .\windows\run.bat"
    Write-Host "  API:       .\venv\Scripts\uvicorn.exe api.main:app --reload"
}
