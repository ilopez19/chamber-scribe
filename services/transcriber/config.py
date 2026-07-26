# Whisper device/model selection and timeout tuning for the transcriber.
import torch
from shared.logging_config import get_logger

logger = get_logger(__name__)

# Automatically use GPU if available
WHISPER_DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
WHISPER_COMPUTE_TYPE = "float16" if torch.cuda.is_available() else "int8"
WHISPER_MODEL = "small"
WHISPER_LANGUAGE = "en"

# Minimum duration in seconds to bother transcribing
MIN_DURATION_SECONDS = 30

# Ceiling on a single transcription attempt (VTT or Whisper). Without this,
# a stuck engine call — e.g. faster-whisper hanging while decoding a
# corrupted/truncated audio file — blocks run_transcriptions() forever, the
# same way an unbounded ffmpeg subprocess blocked the downloader (see
# services/downloader/strategies/hls.py, fixed the same way). Generous on
# purpose: real hearings can run several hours, and CPU-only transcription
# can be slower than real-time, so this should only ever fire on a genuine
# hang, not a long-but-legitimate job.
TRANSCRIBE_TIMEOUT_SECONDS = 3 * 60 * 60  # 3 hours

logger.info(f"Transcriber using: {WHISPER_DEVICE} ({WHISPER_COMPUTE_TYPE})")