import asyncio
import os
from services.downloader.config import DOWNLOAD_TIMEOUT
from services.downloader.strategies.base import BaseDownloadStrategy
from shared.logging_config import get_logger

logger = get_logger(__name__)


# Downloads HLS streams via FFmpeg with -vn (audio only) — much smaller
# and faster than pulling the full video.
class HLSDownloadStrategy(BaseDownloadStrategy):

    async def download(self, url: str, destination: str) -> bool:
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        logger.info(f"[hls] Downloading audio from stream: {url}")
        logger.info(f"[hls] Saving to: {destination}")

        command = [
            "ffmpeg",
            # CloudFront returns 403 for ffmpeg's default User-Agent on this
            # distribution — a browser UA gets past whatever blocks it.
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
                # Without a timeout a stalled read leaves ffmpeg running
                # forever, hanging the whole downloader_loop cycle (and its
                # heartbeat) along with it.
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=DOWNLOAD_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error(f"[hls] ❌ FFmpeg timed out after {DOWNLOAD_TIMEOUT}s — killing: {url}")
                process.kill()
                await process.wait()
                self._remove_partial_file(destination)
                return False

            if process.returncode == 0:
                # Decimal MB (1e6), not binary MiB (2**20) — matches every
                # other size calc in this codebase.
                size_mb = round(os.path.getsize(destination) / 1_000_000, 1)
                logger.info(f"[hls] ✅ Audio extracted: {destination} ({size_mb}MB)")
                return True
            else:
                error = stderr.decode()[-500:]
                logger.error(f"[hls] ❌ FFmpeg failed: {error}")
                # A failed run can leave a partial file that the downloader's
                # "already on disk" check would treat as complete forever.
                self._remove_partial_file(destination)
                return False

        except FileNotFoundError:
            logger.error("[hls] ❌ FFmpeg not found — make sure it's on PATH")
            return False
        except Exception as e:
            logger.error(f"[hls] ❌ Unexpected error: {e}")
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            self._remove_partial_file(destination)
            return False

    @staticmethod
    def _remove_partial_file(destination: str) -> None:
        if os.path.exists(destination):
            try:
                os.remove(destination)
            except OSError:
                pass
