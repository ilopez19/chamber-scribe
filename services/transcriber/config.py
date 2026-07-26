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

logger.info(f"Transcriber using: {WHISPER_DEVICE} ({WHISPER_COMPUTE_TYPE})")