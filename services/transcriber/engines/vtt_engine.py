"""
VTT transcription engine.

Parses a WebVTT caption file into the same transcript format
that WhisperEngine produces. This lets the transcriber treat
VTT and Whisper output identically downstream.

For captioned Senate videos this replaces Whisper entirely —
near-instant vs minutes of GPU time.
"""

import re
from services.transcriber.engines.base import BaseTranscriptionEngine


def _parse_timestamp(ts: str) -> float:
    """
    Convert a VTT timestamp to seconds.

    Handles all common formats:
      0:00:01.400     (H:MM:SS.mmm)
      00:00:01.400    (HH:MM:SS.mmm)
      00:01.400       (MM:SS.mmm)
    """
    try:
        ts = ts.strip()
        # Split off milliseconds first
        if "." in ts:
            time_part, ms_part = ts.rsplit(".", 1)
            ms = float("0." + ms_part)
        else:
            time_part = ts
            ms = 0.0

        parts = time_part.split(":")

        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + int(s) + ms
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + int(s) + ms
        else:
            return int(parts[0]) + ms

    except Exception:
        return 0.0

def parse_vtt(vtt_path: str) -> list[dict]:
    """
    Parse a .vtt file into a list of segment dicts.

    Each segment matches the faster-whisper output format:
        {"start": float, "end": float, "text": str}
    """
    segments = []

    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split into blocks by blank lines
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]

        if not lines:
            continue

        # Skip header lines
        if lines[0].startswith("WEBVTT") or lines[0].startswith("Kind:") or lines[0].startswith("Language:"):
            continue

        # Find the timestamp line — contains "-->"
        ts_line = None
        text_lines = []

        for i, line in enumerate(lines):
            if "-->" in line:
                ts_line = line
                text_lines = lines[i + 1:]
                break

        if not ts_line or not text_lines:
            continue

        # Parse timestamps
        try:
            # Typical line: "00:00:01.400 --> 00:00:04.200"
            parts = ts_line.split("-->")
            if len(parts) != 2:
                continue
            start_str = parts[0].strip()
            # Strip any trailing metadata after the end timestamp
            end_str = parts[1].strip().split()[0]
        except ValueError:
            continue

        # Join text lines into one segment
        text = " ".join(text_lines).strip()
        if not text:
            continue

        # Convert timestamps to seconds using the helper and round for
        # consistency with Whisper segments. Using a helper centralizes
        # parsing logic for different timestamp formats.
        start = _parse_timestamp(start_str)
        end = _parse_timestamp(end_str)

        segments.append({
            "start": round(start, 2),
            "end":   round(end, 2),
            "text":  text,
        })

    return segments


class VTTEngine(BaseTranscriptionEngine):
    """
    Transcription engine that reads from a pre-existing VTT caption file
    instead of running Whisper.

    Used for Senate videos where captioned=True — the VTT is already
    downloaded by the downloader as part of the DownloadPlan.
    """

    async def transcribe(self, audio_path: str) -> dict:
        """
        audio_path is the .mp3 path — we derive the .vtt path from it.

        Convention:
            audio:   storage/audio/michigan_senate/{portal_id}.mp3
            caption: storage/captions/michigan_senate/{portal_id}.vtt
        """
        vtt_path = self._find_vtt(audio_path)

        if not vtt_path:
            raise FileNotFoundError(
                f"No VTT caption file found for audio: {audio_path}. "
                f"Expected at: {self._expected_vtt_path(audio_path)}"
            )

        segments = parse_vtt(vtt_path)

        if not segments:
            raise ValueError(f"VTT file parsed but contained no segments: {vtt_path}")

        full_text = " ".join(s["text"] for s in segments)

        return {
            "text":     full_text,
            "segments": segments,
            "language": "en",
            "engine":   "vtt-caption",
        }

    def _expected_vtt_path(self, audio_path: str) -> str:
        """Derive the expected VTT path from an audio path."""
        import os
        filename = os.path.basename(audio_path)
        portal_id = filename.replace(".mp3", "")
        source = audio_path.split(os.sep)[-2] if os.sep in audio_path else "unknown"
        return os.path.join("storage", "captions", source, f"{portal_id}.vtt")

    def _find_vtt(self, audio_path: str) -> str | None:
        """Return VTT path if it exists, else None."""
        import os
        vtt_path = self._expected_vtt_path(audio_path)
        return vtt_path if os.path.exists(vtt_path) else None