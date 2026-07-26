import asyncio
import os
import httpx
from services.downloader.config import (
    DOWNLOAD_CHUNK_SIZE,
    DOWNLOAD_MAX_RETRIES,
    DOWNLOAD_RETRY_DELAY,
    DOWNLOAD_TIMEOUT,
)
from services.downloader.strategies.base import BaseDownloadStrategy
from shared.logging_config import get_logger

logger = get_logger(__name__)


class HTTPDownloadStrategy(BaseDownloadStrategy):
    """
    Downloads files over HTTP in chunks.
    Handles large files without loading them fully into memory.
    """

    def __init__(self, verify_ssl: bool = True):
        self._verify = verify_ssl

    async def download(self, url: str, destination: str) -> bool:
        """
        Stream download a file in chunks to disk.

        Args:
            url: URL to download from
            destination: Full file path to save to

        Returns:
            True if download succeeded
        """
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        for attempt in range(DOWNLOAD_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(
                        timeout=DOWNLOAD_TIMEOUT,
                        verify=self._verify,
                        follow_redirects=True,
                ) as client:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()

                        # Check file size before downloading
                        total = int(response.headers.get("content-length", 0))
                        downloaded = 0

                        with open(destination, "wb") as f:
                            async for chunk in response.aiter_bytes(DOWNLOAD_CHUNK_SIZE):
                                f.write(chunk)
                                downloaded += len(chunk)

                                if total:
                                    pct = round((downloaded / total) * 100, 1)
                                    print(
                                        f"[http] {os.path.basename(destination)} "
                                        f"{pct}% ({downloaded // 1_000_000}MB / {total // 1_000_000}MB)",
                                        end="\r",
                                    )

                        print()  # newline after progress

                        # NOTE: the server can close the connection early (seen in
                        # practice with House's flaky TLS setup) and aiter_bytes()
                        # ends normally without raising. Without this check we'd
                        # silently accept a truncated file as a successful download.
                        if total and downloaded != total:
                            os.remove(destination)
                            raise httpx.RequestError(
                                f"Incomplete download: got {downloaded}/{total} bytes",
                                request=response.request,
                            )

                        return True

            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                if attempt >= DOWNLOAD_MAX_RETRIES:
                    logger.error(f"\n[http] Failed after {DOWNLOAD_MAX_RETRIES} retries: {url} — {e}")
                    return False

                delay = DOWNLOAD_RETRY_DELAY * (2 ** attempt)
                logger.warning(f"\n[http] Retry {attempt + 1}/{DOWNLOAD_MAX_RETRIES} in {delay}s — {e}")
                await asyncio.sleep(delay)

        return False