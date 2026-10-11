"""Regression tests for FyersClient's 429 retry-with-backoff. The old
per-instance per-second throttle test lived here; that throttle was replaced
by the process-wide limiter in request_control.py (Phase 0), which has its
own tests in test_fyers_request_control.py. Uses httpx.MockTransport so no
real network call or external mocking library is needed."""

import asyncio

import httpx
import pytest

from app.config import Settings
from app.core.exceptions import FyersRateLimitError
from app.integrations.fyers.fyers_client import FyersClient


def _settings() -> Settings:
    # Cooldown disabled here: these tests are about tenacity's retry, and
    # asyncio.sleep is stubbed out, so a real cooldown would just spin.
    return Settings(
        use_mock_fyers=False, fyers_client_id="test-client", fyers_access_token="test-token",
        fyers_429_cooldown_seconds=0,
    )


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Retries would otherwise sleep for real seconds (tenacity's
    wait_exponential) -- keep the test fast and deterministic without
    weakening what's being tested."""

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
