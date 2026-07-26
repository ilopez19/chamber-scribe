#!/usr/bin/env bash
# Stops whatever start.sh started, using the PIDs it saved to .run/.
# Safe to run even if nothing is running (says so and exits cleanly).
#
# Run from the repo root:  ./stop.sh
# This is a hard stop (kill), not a graceful shutdown request: a download
# or transcription in progress gets killed mid-work rather than finishing
# first. That's fine - claim_jobs()'s re-claim logic in downloader.py/
# transcriber.py picks up anything left stuck on the next start, instead
# of it staying stuck forever.
# Windows: use stop.ps1 instead.

stop_tracked() {
    local name="$1" pidfile="$2"
    if [ ! -f "$pidfile" ]; then
        echo "$name is not running (no PID file)."
        return
    fi
    local pid
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        echo "Stopped $name (PID $pid)."
    else
        echo "$name PID file exists but that process isn't running (already stopped)."
    fi
    rm -f "$pidfile"
}

stop_tracked "Pipeline" ".run/pipeline.pid"
stop_tracked "API" ".run/api.pid"
