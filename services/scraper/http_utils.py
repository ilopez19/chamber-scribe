"""
Shared HTTP utilities for detectors.

Provides:
- Consistent HTTP client configuration
- Retry logic with exponential backoff
- Common request patterns
"""

import asyncio
import httpx
from typing import Optional
from services.scraper.config import HTTP_TIMEOUT, HTTP_VERIFY, MAX_RETRIES, RETRY_DELAY
from shared.logging_config import get_logger

logger = get_logger(__name__)


class HTTPClient:
    """Manages shared HTTP client with consistent configuration."""

    @staticmethod
    def create_client(
        timeout: int = HTTP_TIMEOUT,
        verify: bool = HTTP_VERIFY,
        **kwargs
    ) -> httpx.AsyncClient:
        """
        Create a configured AsyncClient.

        Args:
            timeout: Request timeout in seconds
            verify: Enable/disable SSL verification
            **kwargs: Additional httpx.AsyncClient arguments

        Returns:
            Configured AsyncClient instance
        """
        return httpx.AsyncClient(timeout=timeout, verify=verify, **kwargs)


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int = MAX_RETRIES,
    retry_delay: float = RETRY_DELAY,
    **kwargs
) -> Optional[httpx.Response]:
    """
    Fetch URL with exponential backoff retry logic.

    Args:
        client: AsyncClient to use
        url: URL to fetch
        max_retries: Number of retry attempts
        retry_delay: Initial delay between retries (doubles each attempt)
        **kwargs: Additional arguments for client.get()

    Returns:
        Response object or None if all retries failed

    Raises:
        httpx.HTTPStatusError: If response status indicates error (after retries exhausted)
    """
    delay = retry_delay
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url, **kwargs)
            response.raise_for_status()
            return response
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            if attempt >= max_retries:
                raise  # Re-raise on final attempt
            logger.warning(f"[http_utils] Retry {attempt + 1}/{max_retries} after {delay}s: {url} — {e}")
            await asyncio.sleep(delay)
            delay *= 2  # Exponential backoff

    return None

