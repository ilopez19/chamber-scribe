from abc import ABC, abstractmethod
from typing import Optional
import httpx
from services.scraper.http_utils import HTTPClient


class BaseDetector(ABC):
    """Base interface for all video detectors.

    Subclasses must implement the `source_name` property and the
    `get_new_videos` coroutine method.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique identifier for this video source."""
        raise NotImplementedError

    @abstractmethod
    async def get_new_videos(self) -> list[dict]:
        """Fetch new videos from this source.

        Returns:
            List of dicts with keys: video_url, metadata
        """
        raise NotImplementedError


class HTTPDetector(BaseDetector):
    """
    Base class for detectors that fetch from HTTP sources.

    Provides shared HTTP client management and consistent configuration.
    """

    def __init__(self, timeout: int = 30, verify: bool = True):
        self._timeout = timeout
        self._verify = verify
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create a shared HTTP client for the detector."""
        if self._client is None:
            self._client = HTTPClient.create_client(timeout=self._timeout, verify=self._verify)
        return self._client

    async def close_client(self) -> None:
        """Close the detector's HTTP client if open."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_client()

