#!/usr/bin/env bash
# Starts the pipeline (main.py) and the REST API (uvicorn) as background
# processes, so this terminal is free again immediately. PIDs are saved
# to .run/ so stop.sh and restart.sh know what to stop later.
#
# Run from the repo root:  ./start.sh
# Logs go to logs/pipeline.out.log / logs/api.out.log.
# Refuses to start a second copy if one's already running - use
# ./restart.sh instead.
# Windows: use start.ps1 instead.

set -uo pipefail

is_running() {
    [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null
}

if [ ! -f "venv/bin/python3" ]; then
    echo "No venv found - run ./install.sh first."
    exit 1
fi

mkdir -p .run logs

if is_running ".run/pipeline.pid" || is_running ".run/api.pid"; then
    echo "Already running. Use ./restart.sh to restart, or ./stop.sh first."
    exit 1
fi

nohup venv/bin/python3 main.py > logs/pipeline.out.log 2>&1 &
echo $! > .run/pipeline.pid
echo "Pipeline started (PID $(cat .run/pipeline.pid)) - logs/pipeline.out.log"

nohup venv/bin/python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 > logs/api.out.log 2>&1 &
echo $! > .run/api.pid
echo "API started (PID $(cat .run/api.pid)) - http://localhost:8000"

echo ""
echo "Both running in the background."
echo "  Check health:  curl http://localhost:8000/health"
echo "  Stop:          ./stop.sh"
echo "  Restart:       ./restart.sh"
