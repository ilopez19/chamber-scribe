<#
.SYNOPSIS
    Stops whatever start.ps1 started, using the PIDs it saved to .run\.

.NOTES
    Run from the repo root:  .\stop.ps1
    Safe to run even if nothing is running - just says so and exits cleanly.
    This is a hard stop (Stop-Process), not a graceful shutdown request: a
    download or transcription in progress gets killed mid-work rather than
    finishing first. That's fine - claim_jobs()'s re-claim logic in
    downloader.py/transcriber.py picks up anything left stuck on the next
    start, instead of it staying stuck forever.
#>

function Stop-Tracked($name, $pidFile) {
    if (-not (Test-Path $pidFile)) {
        Write-Host "$name is not running (no PID file)." -ForegroundColor Yellow
        return
    }
    $targetId = Get-Content $pidFile -ErrorAction SilentlyContinue
    $proc = if ($targetId) { Get-Process -Id $targetId -ErrorAction SilentlyContinue } else { $null }
    if ($proc) {
        Stop-Process -Id $targetId -Force
        Write-Host "Stopped $name (PID $targetId)." -ForegroundColor Green
    } else {
        Write-Host "$name PID file exists but that process isn't running (already stopped)." -ForegroundColor Yellow
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

Stop-Tracked "Pipeline" ".run\pipeline.pid"
Stop-Tracked "API" ".run\api.pid"
