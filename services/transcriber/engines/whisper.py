import asyncio
from faster_whisper import WhisperModel
from services.transcriber.engines.base import BaseTranscriptionEngine
from services.transcriber.config import (
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_MODEL,
    WHISPER_LANGUAGE,
)

"""Whisper transcription engine wrapper.

This module lazily loads the faster-whisper model (cached in-process) and
provides a small adapter that runs the synchronous transcription in a thread
pool so the surrounding async code can await it.
"""

_model = None


def get_model() -> WhisperModel:
    """Load the WhisperModel lazily and cache it for reuse.

    Loading a model can be expensive (~seconds) so we keep a module-level
    cached instance. This function is safe to call from multiple places; the
    first caller pays the load cost.
    """
    global _model
    if _model is None:
        print(f"[whisper] Loading model '{WHISPER_MODEL}' on {WHISPER_DEVICE}...")
        _model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        print(f"[whisper] Model ready.")
    return _model


class WhisperEngine(BaseTranscriptionEngine):
    """Transcribes audio using faster-whisper.

    The heavy synchronous work runs in a threadpool so callers can await the
    result from async code. The engine applies a simple VAD filter to drop
    silence, which reduces model time and output noise.
    """

    async def transcribe(self, audio_path: str) -> dict:
        loop = asyncio.get_event_loop()

        # Run in thread pool — whisper is CPU/GPU bound, not async
        result = await loop.run_in_executor(None, self._run, audio_path)
        return result

    def _run(self, audio_path: str) -> dict:
        model = get_model()
        print(f"[whisper] Transcribing: {audio_path}")

        # Configure the model to apply a small VAD filter to skip long
        # stretches of silence; this tends to improve throughput and reduces
        # the amount of text to post-process.
        segments, info = model.transcribe(
            audio_path,
            language=WHISPER_LANGUAGE,
            beam_size=5,
            vad_filter=True,          # skip silence automatically
            vad_parameters={
                "min_silence_duration_ms": 500,
            },
        )

        # Collect all segments into the shared transcript format
        segment_list = []
        full_text = []

        for segment in segments:
            segment_list.append({
                "start": round(segment.start, 2),
                "end":   round(segment.end, 2),
                "text":  segment.text.strip(),
            })
            full_text.append(segment.text.strip())

        return {
            "text":     " ".join(full_text),
            "segments": segment_list,
            "language": info.language,
            "engine":   f"faster-whisper-{WHISPER_MODEL}",
        }