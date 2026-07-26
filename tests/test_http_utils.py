# Tests for fetch_with_retry() — the shared retry/backoff wrapper every
# detector's HTTP call goes through. Locks down: no retry on first-try
# success, retry-then-succeed on transient failure, doubling backoff, and
# raising (never returning None) once retries are exhausted.

import asyncio

import httpx
import pytest

from services.scraper.http_utils import fetch_with_retry


# Stands in for httpx.Response — raise_for_status() is a no-op (success).
class _FakeResponse:

    def raise_for_status(self):
        pass


# Stands in for httpx.AsyncClient; each .request() call consumes the next
# scripted outcome — an Exception is raised, anything else is returned as-is.
class _FakeClient:

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.call_count = 0

    async def request(self, method, url, **kwargs):
        self.call_count += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_succeeds_on_first_attempt_no_retry_needed():
    client = _FakeClient([_FakeResponse()])
    response = await fetch_with_retry(client, "http://example.test", max_retries=3, retry_delay=0)
    assert response.__class__ is _FakeResponse
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_retries_after_transient_failures_then_succeeds():
    client = _FakeClient([
        httpx.RequestError("connection reset"),
        httpx.RequestError("connection reset"),
        _FakeResponse(),
    ])
    response = await fetch_with_retry(client, "http://example.test", max_retries=3, retry_delay=0)
    assert response.__class__ is _FakeResponse
    # 2 failed attempts + 1 successful attempt
    assert client.call_count == 3


@pytest.mark.asyncio
async def test_raises_after_exhausting_all_retries():
    # max_retries=2 means at most 3 total attempts; every one fails here,
    # so this should raise instead of returning None.
    client = _FakeClient([
        httpx.RequestError("fail 1"),
        httpx.RequestError("fail 2"),
        httpx.RequestError("fail 3"),
    ])
    with pytest.raises(httpx.RequestError):
        await fetch_with_retry(client, "http://example.test", max_retries=2, retry_delay=0)
    assert client.call_count == 3


@pytest.mark.asyncio
async def test_backoff_delay_doubles_each_retry(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = _FakeClient([
        httpx.RequestError("fail 1"),
        httpx.RequestError("fail 2"),
        _FakeResponse(),
    ])
    await fetch_with_retry(client, "http://example.test", max_retries=3, retry_delay=1)

    assert sleeps == [1, 2]


@pytest.mark.asyncio
async def test_http_status_error_is_retried_same_as_request_error():
    # A 500 (HTTPStatusError from raise_for_status()) must be retried
    # exactly like a network-level RequestError, not treated differently.
    class _FailingResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("server error", request=None, response=None)

    client = _FakeClient([_FailingResponse(), _FakeResponse()])
    response = await fetch_with_retry(client, "http://example.test", max_retries=1, retry_delay=0)
    assert response.__class__ is _FakeResponse
    assert client.call_count == 2
