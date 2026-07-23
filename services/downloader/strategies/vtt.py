import os
import httpx
from services.downloader.strategies.base import BaseDownloadStrategy
from services.downloader.config import DOWNLOAD_TIMEOUT


class VTTDownloadStrategy(BaseDownloadStrategy):
    """
    Downloads a WebVTT caption file directly.
    These are plain text files — very fast, kilobytes in size.
    """

    async def download(self, url: str, destination: str) -> bool:
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        try:
            async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
                response = await client.get(url)
                response.raise_for_status()

                with open(destination, "w", encoding="utf-8") as f:
                    f.write(response.text)

                size_kb = round(os.path.getsize(destination) / 1_000, 1)
                print(f"[vtt] ✅ Downloaded: {destination} ({size_kb}KB)")
                return True

        except Exception as e:
            print(f"[vtt] ❌ Failed: {url} — {e}")
            return False