#!/usr/bin/env bash
# One-time setup for Chamber Scribe on macOS/Linux: Python virtual
# environment + deps, FFmpeg, and MongoDB - installing FFmpeg/MongoDB via
# Homebrew if they aren't already on this machine.
#
# Run from the repo root:  ./macos-linux/install.sh   (or: bash macos-linux/install.sh)
# Safe to re-run - every step checks whether it's already done first.
# Windows: use windows\install.ps1 instead.

set -uo pipefail

# Lives in macos-linux/ but operates on the repo root - works whether it's
# invoked as ./macos-linux/install.sh from the root, or run directly from
# inside macos-linux/.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

step() { echo ""; echo "== $1 =="; }
has() { command -v "$1" >/dev/null 2>&1; }

# -- 0. Sanity checks ---------------------------------------------------------
step "Checking prerequisites"

HAS_BREW=0
if has brew; then
    HAS_BREW=1
else
    echo "Homebrew not found - FFmpeg/MongoDB/Python auto-install will be skipped. Install it from https://brew.sh, or install things manually (links below if needed)."
fi

if ! has python3; then
    echo "python3 not found."

    if [ "$HAS_BREW" -eq 1 ]; then
        read -r -p "Install Python 3.12 now via Homebrew? (y/N) " installPython
        if [ "$installPython" = "y" ] || [ "$installPython" = "Y" ]; then
            brew install python@3.12
        else
            echo "Skipping Python install."
        fi
    fi

    if ! has python3; then
        echo "python3 still not found. Install Python 3.12+ (https://www.python.org/downloads/, or 'brew install python@3.12'), make sure it's on PATH, then re-run this script."
        exit 1
    fi
    echo "Python is now available."
fi

# -- 1. Python virtual environment + dependencies -----------------------------
step "Python virtual environment"

if [ ! -f "venv/bin/python3" ]; then
    echo "Creating venv..."
    python3 -m venv venv
else
    echo "venv already exists - skipping creation."
fi

step "Installing Python dependencies"
venv/bin/python3 -m pip install --upgrade pip
if ! venv/bin/python3 -m pip install -r requirements.txt; then
    echo "pip failed to install requirements.txt (see errors above) - stopping so the rest of the script doesn't run against a broken environment."
    exit 1
fi

# torch isn't pinned in requirements.txt (see the comment there) - it's
# installed here instead, separately, so a stale/unavailable torch build
# can't take the other packages down with it. Unlike Windows, plain
# `pip install torch` on macOS/Linux already includes Apple Silicon
# (MPS/Metal) support automatically where applicable - no separate CUDA
# index-url selection needed here. On Linux with an NVIDIA GPU, a CUDA
# build can be installed manually afterward the same way windows\install.ps1
# does it (see that file for the index-url pattern) if GPU acceleration matters.
step "Installing PyTorch"
if ! venv/bin/python3 -m pip install torch; then
    echo "torch failed to install (see errors above). The app needs it to run - fix the error and re-run this script."
    exit 1
fi

# -- 2. FFmpeg ------------------------------------------------------------------
step "FFmpeg"

if has ffmpeg; then
    echo "FFmpeg already installed - skipping."
elif [ "$HAS_BREW" -eq 1 ]; then
    echo "Installing FFmpeg via Homebrew..."
    brew install ffmpeg
else
    echo "Install FFmpeg manually: https://ffmpeg.org/download.html (make sure ffmpeg ends up on PATH)."
fi

# -- 3. MongoDB -------------------------------------------------------------------
step "MongoDB"

if has mongod; then
    echo "MongoDB already installed - skipping install."
elif [ "$HAS_BREW" -eq 1 ]; then
    echo "Installing MongoDB Community Server via Homebrew..."
    brew tap mongodb/brew
    brew install mongodb-community
else
    echo "Install MongoDB manually: https://www.mongodb.com/try/download/community"
fi

if [ "$HAS_BREW" -eq 1 ]; then
    echo "Starting MongoDB (brew services)..."
    if ! brew services start mongodb-community >/dev/null 2>&1; then
        echo "Could not start MongoDB via brew services - start it manually if needed (e.g. 'mongod --config /usr/local/etc/mongod.conf')."
    fi
fi

# -- 4. .env ------------------------------------------------------------------------
step "Environment file"

if [ ! -f ".env" ]; then
    cp ".env.example" ".env"
    echo "Created .env from .env.example. Defaults already point at a local MongoDB instance (mongodb://localhost:27017) - edit .env if yours differs."
else
    echo ".env already exists - leaving it as-is."
fi

# -- Done -----------------------------------------------------------------------------
step "Setup complete"
echo "Sanity check the database connection:  venv/bin/python3 -m scripts.db_utils summary"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
read -r -p "Start Chamber Scribe now (pipeline + API in the background)? (y/N) " startNow
if [ "$startNow" = "y" ] || [ "$startNow" = "Y" ]; then
    "$SCRIPT_DIR/start.sh"
else
    echo "Start it later with:  ./macos-linux/start.sh"
    echo "Or run it in the foreground instead:"
    echo "  Pipeline:  ./macos-linux/run.sh"
    echo "  API:       venv/bin/uvicorn api.main:app --reload"
fi
