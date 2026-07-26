import asyncio
import os
from services.downloader.config import DOWNLOAD_TIMEOUT
from services.downloader.strategies.base import BaseDownloadStrategy
from shared.logging_config import get_logger

logger = get_logger(__name__)


# Extracts audio directly from a progressive HTTP(S) video URL via FFmpeg;
# the video is never written to disk, only the mono 16kHz audio track.
# Replaces an earlier approach that raw-downloaded House's full multi-GB video.
class HTTPAudioExtractStrategy(BaseDownloadStrategy):

    # __init__(verify_ssl) is inherited from BaseDownloadStrategy — sets
    # self._verify, used below to skip cert checking for House's broken TLS.

    async def download(self, url: str, destination: str) -> bool:
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        logger.info(f"[http_audio] Extracting audio from: {url}")
        logger.info(f"[http_audio] Saving to: {destination}")

        command = ["ffmpeg"]
        if not self._verify:
            command += ["-tls_verify", "0"]
        command += [
            "-i", url,
            "-vn",                      # no video — audio only, never written to disk
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
                # Same guard as hls.py: without a timeout a stalled read from
                # a flaky House URL leaves ffmpeg running forever.
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=DOWNLOAD_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error(f"[http_audio] FFmpeg timed out after {DOWNLOAD_TIMEOUT}s - killing: {url}")
                process.kill()
                await process.wait()
                self._cleanup_partial(destination)
                return False

            if process.returncode == 0:
                # Decimal MB (1e6), not binary MiB (2**20) — matches every
                # other size calc in this codebase.
                size_mb = round(os.path.getsize(destination) / 1_000_000, 1)
                logger.info(f"[http_audio] Audio extracted: {destination} ({size_mb}MB)")
                return True
            else:
                error = stderr.decode()[-500:]
                logger.error(f"[http_audio] FFmpeg failed: {error}")
                # See hls.py: a failed run can leave a partial file the
                # "already on disk" check would treat as complete forever.
                self._cleanup_partial(destination)
                return False

        except FileNotFoundError:
            logger.error("[http_audio] FFmpeg not found - make sure it's on PATH")
            return False
        except Exception as e:
            logger.error(f"[http_audio] Unexpected error: {e}")
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
