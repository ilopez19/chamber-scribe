#!/usr/bin/env bash
# Activates the venv and runs main.py in the foreground.
# macOS/Linux equivalent of run.bat.
set -e
source venv/bin/activate
python3 main.py
