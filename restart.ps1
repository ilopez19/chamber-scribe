<#
.SYNOPSIS
    Stops and restarts the pipeline + API - shorthand for .\stop.ps1
    followed by .\start.ps1.

.NOTES
    Run from the repo root:  .\restart.ps1
#>

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

& "$scriptDir\stop.ps1"
Start-Sleep -Seconds 1
& "$scriptDir\start.ps1"
