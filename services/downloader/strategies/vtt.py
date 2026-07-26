# Download strategy for pre-existing WebVTT captions (Senate portal).
import os
import httpx
from services.downloader.strategies.base import BaseDownloadStrategy
from services.downloader.config import DOWNLOAD_TIMEOUT
from shared.logging_config import get_logger

logger = get_logger(__name__)


# Downloads a WebVTT caption file directly — plain text, kilobytes in size.
class VTTDownloadStrategy(BaseDownloadStrategy):

    async def download(self, url: str, destination: str) -> bool:
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        try:
            async with httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT) as client:
                response = await client.get(url)
                response.raise_for_status()

                with open(destination, "w", encoding="utf-8") as f:
                    f.write(response.text)

                # Decimal KB (1e3), not binary KiB (2**10) — same convention
                # as every other size calc in this codebase.
                size_kb = round(os.path.getsize(destination) / 1_000, 1)
                logger.info(f"[vtt] Downloaded: {destination} ({size_kb}KB)")
                return True

        except Exception as e:
            logger.error(f"[vtt] Failed: {url} - {e}")
            return False
