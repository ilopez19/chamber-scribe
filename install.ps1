<#
.SYNOPSIS
    One-time setup for Chamber Scribe: Python virtual environment + deps,
    FFmpeg, and MongoDB - installing FFmpeg/MongoDB via winget if they
    aren't already on this machine.

.NOTES
    Run from the repo root:  .\install.ps1
    Safe to re-run - every step checks whether it's already done first.
#>

$ErrorActionPreference = "Stop"

function Test-CommandExists($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Write-Step($msg) {
    Write-Host ""
    Write-Host "== $msg ==" -ForegroundColor Cyan
}

# -- 0. Sanity checks ---------------------------------------------------------
Write-Step "Checking prerequisites"

if (-not (Test-CommandExists "python")) {
    Write-Host "Python not found on PATH. Install Python 3.12+ from https://www.python.org/downloads/ (check 'Add python.exe to PATH' during install), then re-run this script." -ForegroundColor Red
    exit 1
}

$hasWinget = Test-CommandExists "winget"
if (-not $hasWinget) {
    Write-Host "winget not found - FFmpeg/MongoDB auto-install will be skipped. Install App Installer from the Microsoft Store to get winget, or install them manually (links below if needed)." -ForegroundColor Yellow
}

# -- 1. Python virtual environment + dependencies -----------------------------
Write-Step "Python virtual environment"

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Creating venv..."
    python -m venv venv
} else {
    Write-Host "venv already exists - skipping creation."
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
Write-Host "Run the pipeline (scraper + downloader + transcriber):  .\run.bat"
Write-Host "Run the API:                                            .\venv\Scripts\uvicorn.exe api.main:app --reload"
Write-Host ""
Write-Host "Sanity check the database connection:  .\venv\Scripts\python.exe -m scripts.db_utils summary"
