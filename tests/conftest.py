"""Shared pytest setup.

These tests exercise business logic (should_transcribe, VTT parsing,
download rules, dedup, portal validation, atomic job claiming), not real
database/GPU/model behavior. Two things need to be true before any
application module gets imported, so this happens in conftest.py, which
pytest loads before collecting test files:

1. shared/config.py reads MONGO_URI/MONGO_DB_NAME/SCRAPE_INTERVAL_SECONDS
   from the environment at import time with no defaults (intentional —
   fail fast in real deployments rather than silently using the wrong
   database). Tests aren't a real deployment, so safe defaults are set
   here if they're not already present.

2. services/transcriber/config.py imports torch at module level to check
   torch.cuda.is_available(), and the whisper engine imports
   faster-whisper. Both are legitimate runtime dependencies (installed by
   install.ps1) but are multi-GB and GPU-related — a unit test suite
   shouldn't need either just to test a pure function like
   should_transcribe(). Stubbing them in sys.modules before they're
   imported lets the real transcriber module chain import successfully
   without either package actually being installed.
"""

import os
import sys
import types

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "chamber_scribe_test")
os.environ.setdefault("SCRAPE_INTERVAL_SECONDS", "3600")

if "torch" not in sys.modules:
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    sys.modules["torch"] = fake_torch

if "faster_whisper" not in sys.modules:
    fake_faster_whisper = types.ModuleType("faster_whisper")

    class _FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, *args, **kwargs):
            raise NotImplementedError("faster_whisper is stubbed out for tests")

    fake_faster_whisper.WhisperModel = _FakeWhisperModel
    sys.modules["faster_whisper"] = fake_faster_whisper
