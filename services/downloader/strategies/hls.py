import asyncio
import os
from services.downloader.strategies.base import BaseDownloadStrategy
from shared.logging_config import get_logger

logger = get_logger(__name__)


class HLSDownloadStrategy(BaseDownloadStrategy):
    """
    Downloads HLS streams using FFmpeg.
    Uses -vn flag to extract audio only — ignores video entirely.
    Much faster and smaller than downloading full video.
    """

    async def download(self, url: str, destination: str) -> bool:
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        logger.info(f"[hls] Downloading audio from stream: {url}")
        logger.info(f"[hls] Saving to: {destination}")

        command = [
            "ffmpeg",
            # CloudFront returns 403 for ffmpeg's default User-Agent
            # ("Lavf/...") on this distribution — pretending to be a
            # browser gets past whatever's checking it (WAF rule or
            # CloudFront Function, most likely).
            "-user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "-i", url,
            "-vn",                      # no video — audio only
            "-acodec", "mp3",           # encode to mp3
            "-ar", "16000",             # 16kHz — optimal for Whisper
            "-ac", "1",                 # mono — reduces file size
            "-q:a", "2",               # quality level
            "-y",                       # overwrite if exists
            destination,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                size_mb = round(os.path.getsize(destination) / 1_000_000, 1)
                logger.info(f"[hls] ✅ Audio extracted: {destination} ({size_mb}MB)")
                return True
            else:
                error = stderr.decode()[-500:]
                logger.error(f"[hls] ❌ FFmpeg failed: {error}")
                return False

        except FileNotFoundError:
            logger.error("[hls] ❌ FFmpeg not found — make sure it's on PATH")
            return False
        except Exception as e:
            logger.error(f"[hls] ❌ Unexpected error: {e}")
            return False