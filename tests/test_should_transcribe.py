"""Tests for should_transcribe() — the single business-logic checkpoint
that decides whether a downloaded job is worth transcribing
(services/transcriber/transcriber.py).

The one behavior worth guarding closely here: House jobs never report a
duration at all (metadata.duration_secs is missing, not 0), and treating
"unknown" the same as "too short" would silently skip every House video —
that was a real risk flagged during development, not a hypothetical.
"""

from services.transcriber.transcriber import should_transcribe
from services.transcriber.config import MIN_DURATION_SECONDS


def _job(duration_secs=None):
    metadata = {}
    if duration_secs is not None:
        metadata["duration_secs"] = duration_secs
    return {"metadata": metadata}


def test_long_enough_video_is_worth_transcribing():
    worth_it, reason = should_transcribe(_job(duration_secs=MIN_DURATION_SECONDS + 60))
    assert worth_it is True
    assert reason == ""


def test_too_short_video_is_excluded():
    worth_it, reason = should_transcribe(_job(duration_secs=MIN_DURATION_SECONDS - 1))
    assert worth_it is False
    assert str(MIN_DURATION_SECONDS) in reason


def test_exactly_at_the_minimum_is_worth_transcribing():
    # Boundary check: the check is "< minimum", so exactly the minimum
    # should pass, not fail.
    worth_it, _ = should_transcribe(_job(duration_secs=MIN_DURATION_SECONDS))
    assert worth_it is True


def test_missing_duration_is_not_treated_as_too_short():
    # House jobs never populate duration_secs at all. If this regresses to
    # treating None as 0 (or any number < the minimum), every House video
    # would silently stop being transcribed.
    worth_it, reason = should_transcribe(_job(duration_secs=None))
    assert worth_it is True
    assert reason == ""


def test_zero_duration_is_still_excluded():
    # Unlike missing duration, an explicit 0 is a known, real value and
    # should still be excluded.
    worth_it, _ = should_transcribe(_job(duration_secs=0))
    assert worth_it is False
