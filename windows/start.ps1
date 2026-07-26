<#
.SYNOPSIS
    Starts the pipeline (main.py) and the REST API (uvicorn) as background
    processes, so this terminal is free again immediately. PIDs are saved
    to .run\ so stop.ps1 and restart.ps1 know what to stop later.

.NOTES
    Run from the repo root:  .\windows\start.ps1
    Logs go to logs\pipeline.out.log / logs\api.out.log (and .err.log).
    Refuses to start a second copy if one's already running - use
    .\windows\restart.ps1 instead.
#>

$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)

function Test-Running($pidFile) {
    if (-not (Test-Path $pidFile)) { return $false }
    $trackedId = Get-Content $pidFile -ErrorAction SilentlyContinue
    if (-not $trackedId) { return $false }
    return [bool](Get-Process -Id $trackedId -ErrorAction SilentlyContinue)
}

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "No venv found - run .\windows\install.ps1 first." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path ".run" | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

if ((Test-Running ".run\pipeline.pid") -or (Test-Running ".run\api.pid")) {
    Write-Host "Already running. Use .\windows\restart.ps1 to restart, or .\windows\stop.ps1 first." -ForegroundColor Yellow
    exit 1
}

$pipeline = Start-Process -FilePath ".\venv\Scripts\python.exe" -ArgumentList "main.py" `
    -RedirectStandardOutput "logs\pipeline.out.log" -RedirectStandardError "logs\pipeline.err.log" `
    -WindowStyle Hidden -PassThru
$pipeline.Id | Out-File ".run\pipeline.pid" -Encoding ascii
Write-Host "Pipeline started (PID $($pipeline.Id)) - logs\pipeline.out.log" -ForegroundColor Green

$api = Start-Process -FilePath ".\venv\Scripts\python.exe" -ArgumentList @("-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000") `
    -RedirectStandardOutput "logs\api.out.log" -RedirectStandardError "logs\api.err.log" `
    -WindowStyle Hidden -PassThru
$api.Id | Out-File ".run\api.pid" -Encoding ascii
Write-Host "API started (PID $($api.Id)) - http://localhost:8000" -ForegroundColor Green

Write-Host ""
Write-Host "Both running in the background."
Write-Host "  Check health:  curl http://localhost:8000/health"
Write-Host "  View logs:     Get-Content .\logs\pipeline.out.log -Wait -Tail 50"
Write-Host "                 Get-Content .\logs\api.out.log -Wait -Tail 50"
Write-Host "  Stop:          .\windows\stop.ps1"
Write-Host "  Restart:       .\windows\restart.ps1"
