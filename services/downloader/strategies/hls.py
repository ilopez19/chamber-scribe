import asyncio
import os
from services.downloader.config import DOWNLOAD_TIMEOUT
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

        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                # Without a timeout, a stalled network read (dead
                # connection, a manifest that never finishes, a URL that no
                # longer serves valid HLS) leaves ffmpeg running forever —
                # and since nothing else races this await, the whole
                # downloader_loop cycle (and therefore its heartbeat) hangs
                # with it. This is exactly what a stuck-looking
                # downloader_loop in /health with a growing
                # seconds_since_last_heartbeat usually means.
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=DOWNLOAD_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error(f"[hls] ❌ FFmpeg timed out after {DOWNLOAD_TIMEOUT}s — killing: {url}")
                process.kill()
                await process.wait()
                self._cleanup_partial(destination)
                return False

            if process.returncode == 0:
                size_mb = round(os.path.getsize(destination) / 1_000_000, 1)
                logger.info(f"[hls] ✅ Audio extracted: {destination} ({size_mb}MB)")
                return True
            else:
                error = stderr.decode()[-500:]
                logger.error(f"[hls] ❌ FFmpeg failed: {error}")
                # A non-zero exit can still leave a partial/corrupt file on
                # disk (ffmpeg writes output incrementally before failing).
                # Without removing it, the downloader's "skip if destination
                # already exists" check (downloader.py's _download_job)
                # would treat this failed attempt as a completed download
                # forever, and Whisper would silently transcribe a
                # truncated file instead of the job ever being retried.
                self._cleanup_partial(destination)
                return False

        except FileNotFoundError:
            logger.error("[hls] ❌ FFmpeg not found — make sure it's on PATH")
            return False
        except Exception as e:
            logger.error(f"[hls] ❌ Unexpected error: {e}")
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            self._cleanup_partial(destination)
            return False

    @staticmethod
    def _cleanup_partial(destination: str) -> None:
        if os.path.exists(destination):
            try:
                os.remove(destination)
            except OSError:
                pass