# Shared HTTP client config + retry-with-backoff logic used by detectors.

import asyncio
import httpx
from services.scraper.config import HTTP_TIMEOUT, HTTP_VERIFY, MAX_RETRIES, RETRY_DELAY
from shared.logging_config import get_logger

logger = get_logger(__name__)


# Manages shared HTTP client with consistent configuration.
class HTTPClient:

    @staticmethod
    def create_client(
        timeout: int = HTTP_TIMEOUT,
        verify: bool = HTTP_VERIFY,
        **kwargs
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, verify=verify, **kwargs)


# Fetches url with exponential backoff. max_retries is retries AFTER the
# initial attempt (total attempts = max_retries + 1); always returns a
# real Response or raises — never returns None.
async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int = MAX_RETRIES,
    retry_delay: float = RETRY_DELAY,
    method: str = "GET",
    **kwargs
) -> httpx.Response:
    delay = retry_delay
    for attempt in range(max_retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            if attempt >= max_retries:
                raise  # Re-raise on final attempt
            logger.warning(f"[http_utils] Retry {attempt + 1}/{max_retries} after {delay}s: {url} — {e}")
            await asyncio.sleep(delay)
            delay *= 2  # Exponential backoff
