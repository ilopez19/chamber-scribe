#!/usr/bin/env bash
# Activates the venv and runs main.py in the foreground.
# macOS/Linux equivalent of windows\run.bat.
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source venv/bin/activate
python3 main.py
