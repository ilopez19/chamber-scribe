<#
.SYNOPSIS
    Reverses install.ps1 - removes the Python venv and uninstalls FFmpeg
    and MongoDB (via winget). Use this to test install.ps1 against a
    clean machine.

.NOTES
    Run from the repo root:  .\windows\uninstall.ps1
    Does NOT touch .env, storage/, or MongoDB's data directory - only the
    venv folder and the FFmpeg/MongoDB applications themselves.
#>

$ErrorActionPreference = "Continue"

Set-Location (Split-Path -Parent $PSScriptRoot)

function Write-Step($msg) {
    Write-Host ""
    Write-Host "== $msg ==" -ForegroundColor Cyan
}

function Test-CommandExists($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "This removes the venv folder and uninstalls FFmpeg + MongoDB (via winget)." -ForegroundColor Yellow
Write-Host "MongoDB's data directory is left in place - only the application is removed." -ForegroundColor Yellow
$confirm = Read-Host "Continue? (y/N)"
if ($confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "Cancelled."
    exit 0
}

# -- 1. Python virtual environment ------------------------------------------
Write-Step "Removing Python virtual environment"

if (Test-Path ".\venv") {
    Remove-Item -Recurse -Force ".\venv"
    Write-Host "Removed .\venv" -ForegroundColor Green
} else {
    Write-Host "No venv found - skipping."
}

# -- 2. MongoDB --------------------------------------------------------------
Write-Step "MongoDB"

$svc = Get-Service -Name "MongoDB" -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "Stopping MongoDB service..."
    Stop-Service MongoDB -Force
}

if (Test-CommandExists "winget") {
    Write-Host "Uninstalling MongoDB.Server via winget..."
    winget uninstall -e --id MongoDB.Server --accept-source-agreements
} else {
    Write-Host "winget not found - uninstall MongoDB manually via 'Add or Remove Programs'." -ForegroundColor Yellow
}

# -- 3. FFmpeg ----------------------------------------------------------------
Write-Step "FFmpeg"

if (Test-CommandExists "winget") {
    Write-Host "Uninstalling Gyan.FFmpeg via winget..."
    winget uninstall -e --id Gyan.FFmpeg --accept-source-agreements
} else {
    Write-Host "winget not found - uninstall FFmpeg manually via 'Add or Remove Programs'." -ForegroundColor Yellow
}

# -- Done ---------------------------------------------------------------------
Write-Step "Uninstall complete"
Write-Host "Close and reopen your terminal so PATH changes clear, then run:  .\windows\install.ps1"
