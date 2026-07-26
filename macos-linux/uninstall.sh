#!/usr/bin/env bash
# Reverses install.sh - removes the Python venv and uninstalls FFmpeg and
# MongoDB (via Homebrew). Use this to test install.sh against a clean
# machine.
#
# Run from the repo root:  ./macos-linux/uninstall.sh   (or: bash macos-linux/uninstall.sh)
# Does NOT touch .env, storage/, or MongoDB's data directory - only the
# venv folder and the FFmpeg/MongoDB applications themselves.
# Windows: use windows\uninstall.ps1 instead.

cd "$(dirname "${BASH_SOURCE[0]}")/.."

step() { echo ""; echo "== $1 =="; }
has() { command -v "$1" >/dev/null 2>&1; }

echo "This removes the venv folder and uninstalls FFmpeg + MongoDB (via Homebrew)."
echo "MongoDB's data directory is left in place - only the application is removed."
read -r -p "Continue? (y/N) " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Cancelled."
    exit 0
fi

# -- 1. Python virtual environment ------------------------------------------
step "Removing Python virtual environment"

if [ -d "venv" ]; then
    rm -rf venv
    echo "Removed venv/"
else
    echo "No venv found - skipping."
fi

# -- 2. MongoDB --------------------------------------------------------------
step "MongoDB"

if has brew; then
    brew services stop mongodb-community >/dev/null 2>&1
    echo "Uninstalling mongodb-community via Homebrew..."
    brew uninstall mongodb-community 2>/dev/null || echo "mongodb-community wasn't installed via Homebrew - skipping."
else
    echo "Homebrew not found - uninstall MongoDB manually."
fi

# -- 3. FFmpeg ----------------------------------------------------------------
step "FFmpeg"

if has brew; then
    echo "Uninstalling ffmpeg via Homebrew..."
    brew uninstall ffmpeg 2>/dev/null || echo "ffmpeg wasn't installed via Homebrew - skipping."
else
    echo "Homebrew not found - uninstall FFmpeg manually."
fi

# -- Done ---------------------------------------------------------------------
step "Uninstall complete"
echo "Run:  ./macos-linux/install.sh"
