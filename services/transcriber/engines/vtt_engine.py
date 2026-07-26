# Parses a WebVTT caption file into the same transcript format WhisperEngine
# produces, so the transcriber treats VTT and Whisper output identically —
# for captioned Senate videos this replaces Whisper entirely.

import re
from services.transcriber.engines.base import BaseTranscriptionEngine


# Converts a VTT timestamp (H:MM:SS.mmm, HH:MM:SS.mmm, or MM:SS.mmm) to seconds.
def _parse_timestamp(ts: str) -> float:
    try:
        ts = ts.strip()
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

# Parses a .vtt file into segment dicts matching faster-whisper's output
# format: {"start": float, "end": float, "text": str}.
def parse_vtt(vtt_path: str) -> list[dict]:
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

        start = _parse_timestamp(start_str)
        end = _parse_timestamp(end_str)

        segments.append({
            "start": round(start, 2),
            "end":   round(end, 2),
            "text":  text,
        })

    return segments


# Reads from a pre-existing VTT caption file instead of running Whisper;
# used for Senate videos where captioned=True.
class VTTEngine(BaseTranscriptionEngine):

    # vtt_path is the actual path from the job's file_paths — captioned
    # Senate jobs only ever download a .vtt, never derived from a filename.
    async def transcribe(self, vtt_path: str) -> dict:
        import os

        if not vtt_path or not os.path.exists(vtt_path):
            raise FileNotFoundError(f"No VTT caption file found at: {vtt_path}")

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
