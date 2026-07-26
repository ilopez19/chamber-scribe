import asyncio
import os
from services.downloader.config import DOWNLOAD_TIMEOUT
from services.downloader.strategies.base import BaseDownloadStrategy
from shared.logging_config import get_logger

logger = get_logger(__name__)


class HTTPAudioExtractStrategy(BaseDownloadStrategy):
    """
    Extracts audio directly from a progressive HTTP(S) video URL using
    FFmpeg — the video itself is never downloaded or written to disk, only
    the extracted mono 16kHz audio track.

    This replaces raw-downloading the full video (previously done by
    HTTPDownloadStrategy for House, which saved the entire multi-GB 1080p60
    file under a misleading .mp3 extension). FFmpeg can pull from a plain
    HTTPS URL the same way HLSDownloadStrategy pulls from an .m3u8 manifest,
    so this is that same pattern pointed at a different kind of source.
    """

    def __init__(self, verify_ssl: bool = True):
        # House serves video over HTTPS with a broken cert chain; skip
        # verification only for sources known to have this problem (mirrors
        # HTTPDownloadStrategy's verify_ssl handling in downloader.py).
        self._verify_ssl = verify_ssl

    async def download(self, url: str, destination: str) -> bool:
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        logger.info(f"[http_audio] Extracting audio from: {url}")
        logger.info(f"[http_audio] Saving to: {destination}")

        command = ["ffmpeg"]
        if not self._verify_ssl:
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
                # See hls.py's identical guard: without a timeout here, a
                # stalled read from a flaky/slow House video URL leaves
                # ffmpeg running forever, and since the downloader_loop only
                # heartbeats after this whole call returns, the loop looks
                # dead in /health even though the process is still alive.
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=DOWNLOAD_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error(f"[http_audio] ❌ FFmpeg timed out after {DOWNLOAD_TIMEOUT}s — killing: {url}")
                process.kill()
                await process.wait()
                self._cleanup_partial(destination)
                return False

            if process.returncode == 0:
                size_mb = round(os.path.getsize(destination) / 1_000_000, 1)
                logger.info(f"[http_audio] ✅ Audio extracted: {destination} ({size_mb}MB)")
                return True
            else:
                error = stderr.decode()[-500:]
                logger.error(f"[http_audio] ❌ FFmpeg failed: {error}")
                # See hls.py: a failed run can still leave a partial file
                # that the downloader's "already on disk" check would
                # otherwise treat as a completed download forever.
                self._cleanup_partial(destination)
                return False

        except FileNotFoundError:
            logger.error("[http_audio] ❌ FFmpeg not found — make sure it's on PATH")
            return False
        except Exception as e:
            logger.error(f"[http_audio] ❌ Unexpected error: {e}")
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
