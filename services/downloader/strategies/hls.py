import asyncio
import os
from services.downloader.strategies.base import BaseDownloadStrategy


class HLSDownloadStrategy(BaseDownloadStrategy):
    """
    Downloads HLS streams using FFmpeg.
    Uses -vn flag to extract audio only — ignores video entirely.
    Much faster and smaller than downloading full video.
    """

    async def download(self, url: str, destination: str) -> bool:
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        print(f"[hls] Downloading audio from stream: {url}")
        print(f"[hls] Saving to: {destination}")

        command = [
            "ffmpeg",
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
                print(f"[hls] ✅ Audio extracted: {destination} ({size_mb}MB)")
                return True
            else:
                error = stderr.decode()[-500:]
                print(f"[hls] ❌ FFmpeg failed: {error}")
                return False

        except FileNotFoundError:
            print("[hls] ❌ FFmpeg not found — make sure it's on PATH")
            return False
        except Exception as e:
            print(f"[hls] ❌ Unexpected error: {e}")
            return False