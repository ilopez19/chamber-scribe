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

# Lazily loads the faster-whisper model (cached in-process) and runs the
# synchronous transcription in a thread pool so async code can await it.

_model = None
_device = WHISPER_DEVICE
_compute_type = WHISPER_COMPUTE_TYPE


# Loads and caches the WhisperModel; safe to call from multiple places,
# only the first caller pays the load cost.
def get_model() -> WhisperModel:
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


# Drops to CPU for the rest of this process after a CUDA runtime failure;
# a missing CUDA library fails every GPU attempt identically, so retrying
# on GPU would just burn the retry budget on a guaranteed repeat failure.
def _fall_back_to_cpu():
    global _model, _device, _compute_type
    logger.error("[whisper] CUDA runtime libraries not usable on this machine - falling back to CPU for the rest of this run.")
    _device = "cpu"
    _compute_type = "int8"
    _model = None


# Transcribes audio using faster-whisper; heavy work runs in a threadpool
# so callers can await it from async code, with a VAD filter to drop silence.
class WhisperEngine(BaseTranscriptionEngine):

    async def transcribe(self, audio_path: str) -> dict:
        loop = asyncio.get_event_loop()

        try:
            return await loop.run_in_executor(None, self._run, audio_path)
        except Exception as e:
            # A missing CUDA runtime library (cublas/cudnn) fails every
            # attempt identically — retry once on CPU instead of hitting
            # the same wall through the job's normal retry loop.
            message = str(e).lower()
            if _device == "cuda" and any(s in message for s in ("cublas", "cudnn", "cuda")):
                _fall_back_to_cpu()
                return await loop.run_in_executor(None, self._run, audio_path)
            raise

    def _run(self, audio_path: str) -> dict:
        model = get_model()
        logger.info(f"[whisper] Transcribing: {audio_path}")

        # VAD filter skips long silence, improving throughput and reducing
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
