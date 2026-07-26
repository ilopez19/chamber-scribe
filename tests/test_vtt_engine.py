"""Tests for the VTT caption parser (services/transcriber/engines/vtt_engine.py).

This is the fast path for every captioned Senate video, so a parsing bug
here silently produces wrong or empty transcripts rather than a loud
failure — worth locking down with real tests.
"""

import pytest

from services.transcriber.engines.vtt_engine import _parse_timestamp, parse_vtt, VTTEngine


class TestParseTimestamp:
    def test_hh_mm_ss_millis(self):
        assert _parse_timestamp("00:01:02.500") == pytest.approx(62.5)

    def test_h_mm_ss_millis(self):
        # Single-digit hour, no leading zero
        assert _parse_timestamp("1:00:00.000") == pytest.approx(3600.0)

    def test_mm_ss_millis(self):
        assert _parse_timestamp("02:30.250") == pytest.approx(150.25)

    def test_no_milliseconds(self):
        assert _parse_timestamp("00:00:10") == pytest.approx(10.0)

    def test_whitespace_is_stripped(self):
        assert _parse_timestamp("  00:00:05.000  ") == pytest.approx(5.0)

    def test_garbage_input_returns_zero_instead_of_raising(self):
        # A malformed caption file shouldn't crash the whole transcription —
        # this is the one behavior the try/except in _parse_timestamp exists
        # to guarantee.
        assert _parse_timestamp("not-a-timestamp") == 0.0


class TestParseVtt:
    def _write(self, tmp_path, content: str) -> str:
        path = tmp_path / "captions.vtt"
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_parses_basic_segments(self, tmp_path):
        content = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:04.000\n"
            "Hello, this is the first segment.\n\n"
            "00:00:04.000 --> 00:00:08.000\n"
            "And this is the second.\n"
        )
        segments = parse_vtt(self._write(tmp_path, content))

        assert len(segments) == 2
        assert segments[0] == {"start": 1.0, "end": 4.0, "text": "Hello, this is the first segment."}
        assert segments[1]["text"] == "And this is the second."

    def test_multi_line_cue_text_is_joined(self, tmp_path):
        content = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:04.000\n"
            "Line one\n"
            "line two\n"
        )
        segments = parse_vtt(self._write(tmp_path, content))
        assert segments[0]["text"] == "Line one line two"

    def test_header_metadata_lines_are_skipped(self, tmp_path):
        content = (
            "WEBVTT\n"
            "Kind: captions\n"
            "Language: en\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Only real cue.\n"
        )
        segments = parse_vtt(self._write(tmp_path, content))
        assert len(segments) == 1
        assert segments[0]["text"] == "Only real cue."

    def test_blocks_without_timestamp_are_skipped(self, tmp_path):
        content = (
            "WEBVTT\n\n"
            "NOTE this is a comment block with no timestamp\n\n"
            "00:00:01.000 --> 00:00:02.000\n"
            "Real cue.\n"
        )
        segments = parse_vtt(self._write(tmp_path, content))
        assert len(segments) == 1

    def test_empty_file_returns_no_segments(self, tmp_path):
        segments = parse_vtt(self._write(tmp_path, "WEBVTT\n"))
        assert segments == []


class TestVttEngine:
    @pytest.mark.asyncio
    async def test_transcribe_raises_when_file_missing(self):
        engine = VTTEngine()
        with pytest.raises(FileNotFoundError):
            await engine.transcribe("/nonexistent/path/does-not-exist.vtt")

    @pytest.mark.asyncio
    async def test_transcribe_raises_on_empty_but_present_vtt(self, tmp_path):
        path = tmp_path / "empty.vtt"
        path.write_text("WEBVTT\n", encoding="utf-8")
        engine = VTTEngine()
        with pytest.raises(ValueError):
            await engine.transcribe(str(path))

    @pytest.mark.asyncio
    async def test_transcribe_returns_expected_shape(self, tmp_path):
        content = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000\n"
            "Testing one two.\n"
        )
        path = tmp_path / "captions.vtt"
        path.write_text(content, encoding="utf-8")

        engine = VTTEngine()
        result = await engine.transcribe(str(path))

        assert result["engine"] == "vtt-caption"
        assert result["language"] == "en"
        assert result["text"] == "Testing one two."
        assert len(result["segments"]) == 1
