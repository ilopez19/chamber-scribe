#!/usr/bin/env bash
# Starts the pipeline (main.py) and the REST API (uvicorn) as background
# processes, so this terminal is free again immediately. PIDs are saved
# to .run/ so stop.sh and restart.sh know what to stop later.
#
# Run from the repo root:  ./macos-linux/start.sh
# Logs go to logs/pipeline.out.log / logs/api.out.log.
# Refuses to start a second copy if one's already running - use
# ./macos-linux/restart.sh instead.
# Windows: use windows\start.ps1 instead.

set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

is_running() {
    [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null
}

if [ ! -f "venv/bin/python3" ]; then
    echo "No venv found - run ./macos-linux/install.sh first."
    exit 1
fi

mkdir -p .run logs

if is_running ".run/pipeline.pid" || is_running ".run/api.pid"; then
    echo "Already running. Use ./macos-linux/restart.sh to restart, or ./macos-linux/stop.sh first."
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
echo "  View logs:     tail -f -n 50 logs/pipeline.out.log"
echo "                 tail -f -n 50 logs/api.out.log"
echo "  New videos:    tail -f logs/pipeline.out.log | grep scraper"
echo "  Stop:          ./macos-linux/stop.sh"
echo "  Restart:       ./macos-linux/restart.sh"
