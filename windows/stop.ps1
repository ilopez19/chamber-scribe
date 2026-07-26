<#
.SYNOPSIS
    Stops whatever start.ps1 started, using the PIDs it saved to .run\.

.NOTES
    Run from the repo root:  .\windows\stop.ps1
    Safe to run even if nothing is running - just says so and exits cleanly.
    This is a hard stop (Stop-Process), not a graceful shutdown request: a
    download or transcription in progress gets killed mid-work rather than
    finishing first. That's fine - claim_jobs()'s re-claim logic in
    downloader.py/transcriber.py picks up anything left stuck on the next
    start, instead of it staying stuck forever.
#>

Set-Location (Split-Path -Parent $PSScriptRoot)

function Stop-Tracked($name, $pidFile) {
    if (-not (Test-Path $pidFile)) {
        Write-Host "$name is not running (no PID file)." -ForegroundColor Yellow
        return
    }
    $targetId = Get-Content $pidFile -ErrorAction SilentlyContinue
    $proc = if ($targetId) { Get-Process -Id $targetId -ErrorAction SilentlyContinue } else { $null }
    if ($proc) {
        # taskkill /T kills the whole process tree, not just this PID.
        # Plain Stop-Process only kills the tracked PID itself, leaving any
        # child it spawned (e.g. an in-progress ffmpeg download) running as
        # an orphan that still holds its output file open - which then
        # blocks things like `scripts.db_utils clear-files` from deleting
        # it even after this script reports the pipeline as stopped.
        & taskkill /PID $targetId /T /F | Out-Null
        Write-Host "Stopped $name (PID $targetId, including any child processes)." -ForegroundColor Green
    } else {
        Write-Host "$name PID file exists but that process isn't running (already stopped)." -ForegroundColor Yellow
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

Stop-Tracked "Pipeline" ".run\pipeline.pid"
Stop-Tracked "API" ".run\api.pid"
