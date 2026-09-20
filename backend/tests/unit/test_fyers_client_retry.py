"""Regression tests for the 429 retry-with-backoff and per-second throttle
added to FyersClient (see fyers_client.py's module-level rate-limit comment).
Uses httpx.MockTransport so no real network call or external mocking
library is needed."""

import asyncio

import httpx
import pytest

from app.config import Settings
from app.core.exceptions import FyersRateLimitError
from app.integrations.fyers.fyers_client import FyersClient


def _settings() -> Settings:
    return Settings(use_mock_fyers=False, fyers_client_id="test-client", fyers_access_token="test-token")


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Retries/throttling would otherwise sleep for real seconds (tenacity's
    wait_exponential, our own _throttle) -- keep the test fast and
    deterministic without weakening what's being tested."""

    async def _fast_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


@pytest.mark.asyncio
async def test_429_is_retried_and_eventually_succeeds():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(429, json={"s": "error", "message": "rate limited"})
        return httpx.Response(200, json={"s": "ok", "d": []})

    client = FyersClient(settings=_settings())
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await client.get_data("/quotes", params={"symbols": "NSE:RELIANCE-EQ"})

    assert result == {"s": "ok", "d": []}
    assert calls["count"] == 3  # two 429s, then success -- proves the retry actually happened


@pytest.mark.asyncio
async def test_429_exhausts_retries_and_raises_rate_limit_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"s": "error", "message": "rate limited"})

    client = FyersClient(settings=_settings())
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    with pytest.raises(FyersRateLimitError):
        await client.get_data("/quotes", params={"symbols": "NSE:RELIANCE-EQ"})


@pytest.mark.asyncio
async def test_throttle_delays_once_per_second_budget_is_exceeded(monkeypatch):
    sleep_calls = []

    async def _tracking_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _tracking_sleep)  # overrides the autouse fixture for this test only

    import app.integrations.fyers.fyers_client as fyers_client_module

    client = FyersClient(settings=_settings())
    # Fill the request-time window right up to the per-second budget.
    now = fyers_client_module.time.monotonic()
    for _ in range(fyers_client_module._MAX_REQUESTS_PER_SECOND):
        client._request_times.append(now)

    await client._throttle()

    assert len(sleep_calls) == 1  # the (_MAX_REQUESTS_PER_SECOND + 1)th request had to wait
