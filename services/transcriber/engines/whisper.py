import asyncio
from faster_whisper import WhisperModel
from services.transcriber.engines.base import BaseTranscriptionEngine
from services.transcriber.config import (
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_MODEL,
    WHISPER_LANGUAGE,
)
from shared.logging_config import get_logger

logger = get_logger(__name__)

"""Whisper transcription engine wrapper.

This module lazily loads the faster-whisper model (cached in-process) and
provides a small adapter that runs the synchronous transcription in a thread
pool so the surrounding async code can await it.
"""

_model = None
_device = WHISPER_DEVICE
_compute_type = WHISPER_COMPUTE_TYPE


def get_model() -> WhisperModel:
    """Load the WhisperModel lazily and cache it for reuse.

    Loading a model can be expensive (~seconds) so we keep a module-level
    cached instance. This function is safe to call from multiple places; the
    first caller pays the load cost.
    """
    global _model
    if _model is None:
        logger.info(f"[whisper] Loading model '{WHISPER_MODEL}' on {_device}...")
        _model = WhisperModel(
            WHISPER_MODEL,
            device=_device,
            compute_type=_compute_type,
        )
        logger.info(f"[whisper] Model ready.")
    return _model


def _fall_back_to_cpu():
    """Drop to CPU for the rest of this process after a CUDA runtime failure.

    torch.cuda.is_available() (used in config.py to pick WHISPER_DEVICE)
    only confirms an NVIDIA driver/GPU is present — it doesn't guarantee
    ctranslate2 (faster-whisper's backend) can find the separate CUDA
    runtime libraries it needs (cuBLAS/cuDNN), which torch bundles
    privately and doesn't share. When that's missing, every GPU attempt
    fails identically, so retrying the same job burns its retry budget on
    a guaranteed repeat failure — switch to CPU once and stay there.
    """
    global _model, _device, _compute_type
    logger.error("[whisper] CUDA runtime libraries not usable on this machine — falling back to CPU for the rest of this run.")
    _device = "cpu"
    _compute_type = "int8"
    _model = None


class WhisperEngine(BaseTranscriptionEngine):
    """Transcribes audio using faster-whisper.

    The heavy synchronous work runs in a threadpool so callers can await the
    result from async code. The engine applies a simple VAD filter to drop
    silence, which reduces model time and output noise.
    """

    async def transcribe(self, audio_path: str) -> dict:
        loop = asyncio.get_event_loop()

        # Run in thread pool — whisper is CPU/GPU bound, not async
        try:
            return await loop.run_in_executor(None, self._run, audio_path)
        except Exception as e:
            # A missing CUDA runtime library (cublas/cudnn DLLs) fails
            # every attempt identically — catch that specific class of
            # error and retry once on CPU instead of letting the job's
            # normal retry loop hit the same wall three times.
            message = str(e).lower()
            if _device == "cuda" and any(s in message for s in ("cublas", "cudnn", "cuda")):
                _fall_back_to_cpu()
                return await loop.run_in_executor(None, self._run, audio_path)
            raise

    def _run(self, audio_path: str) -> dict:
        model = get_model()
        logger.info(f"[whisper] Transcribing: {audio_path}")

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