from abc import ABC, abstractmethod
from typing import Optional
import httpx
from services.scraper.http_utils import HTTPClient


# Base interface every detector implements: source_name + get_new_videos().
class BaseDetector(ABC):

    @property
    @abstractmethod
    def source_name(self) -> str:
        raise NotImplementedError

    # Returns a list of dicts with keys: video_url, metadata.
    @abstractmethod
    async def get_new_videos(self) -> list[dict]:
        raise NotImplementedError


# Base class for HTTP-based detectors — shared client management/config.
class HTTPDetector(BaseDetector):

    def __init__(self, timeout: int = 30, verify: bool = True):
        self._timeout = timeout
        self._verify = verify
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = HTTPClient.create_client(timeout=self._timeout, verify=self._verify)
        return self._client

    async def close_client(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_client()
