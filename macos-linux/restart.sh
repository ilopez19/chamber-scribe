#!/usr/bin/env bash
# Stops and restarts the pipeline + API - shorthand for ./stop.sh followed
# by ./start.sh.
#
# Run from the repo root:  ./macos-linux/restart.sh
# Windows: use windows\restart.ps1 instead.

set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$DIR/stop.sh"
sleep 1
"$DIR/start.sh"
