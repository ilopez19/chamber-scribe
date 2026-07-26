# Shared pytest setup. These tests exercise business logic, not real
# database/GPU/model behavior, so two things are stubbed here before any
# application module gets imported (pytest loads this before collecting tests).
#
# 1. shared/config.py reads Mongo env vars with no defaults (fail-fast in
#    real deployments) — safe test defaults are set here instead.
# 2. transcriber/config.py imports torch/faster-whisper at module level;
#    both are multi-GB GPU deps a unit test suite shouldn't need, so
#    they're stubbed in sys.modules before anything imports them for real.

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
