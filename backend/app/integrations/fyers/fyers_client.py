"""Low-level async HTTP client for FYERS API v3.

Mirrors the REST surface of the official `fyers-apiv3` Python SDK
(https://myapi.fyers.in/docsv3): base URL https://api-t1.fyers.in/api/v3 for
trading/account endpoints, https://api-t1.fyers.in/data for market-data
endpoints. Credentials come only from Settings (env vars) -- never hard-coded,
never echoed to the frontend.

When settings.use_mock_fyers is true, calls short-circuit to canned payloads
from mock_responses.py so the rest of the pipeline is testable without a live
FYERS account.
"""

import asyncio
import time
from collections import deque
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import FyersApiError, FyersAuthError, FyersRateLimitError
from app.logging_config import get_logger

logger = get_logger(__name__)

TRADING_BASE_URL = "https://api-t1.fyers.in/api/v3"
DATA_BASE_URL = "https://api-t1.fyers.in/data"

# Confirmed live cap: 10 req/sec, 200/min, 100,000/day -- breaching the
# per-minute cap 3x in a day gets the whole account blocked for the rest of
# the day. Throttle to 8/sec (not 10) to leave headroom for network jitter;
# this is a per-instance limit, which matches how the app actually uses
# FyersClient -- a fresh instance per scanner run (see scanner_service.py).
_MAX_REQUESTS_PER_SECOND = 8


class FyersClient:
    """Thin async wrapper around FYERS v3 REST endpoints.

    All higher-level adapters (quotes.py, historical_data.py, fno.py,
    market_data.py) go through this client so retry, auth-header, and
    error-normalization logic lives in exactly one place.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client = httpx.AsyncClient(timeout=10.0)
        self._request_times: deque[float] = deque()
        self._throttle_lock = asyncio.Lock()

    @property
    def use_mock(self) -> bool:
        return self.settings.use_mock_fyers

    def _auth_header(self) -> dict[str, str]:
        if not self.settings.fyers_client_id or not self.settings.fyers_access_token:
            raise FyersAuthError(
                "FYERS credentials missing: set FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN, "
                "or enable USE_MOCK_FYERS=true for local development."
            )
        return {"Authorization": f"{self.settings.fyers_client_id}:{self.settings.fyers_access_token}"}

    async def _throttle(self) -> None:
        """Blocks until issuing another request would stay under
        _MAX_REQUESTS_PER_SECOND, using a sliding 1-second window. A 20-stock
        scan used to fire ~40-49 sequential requests in ~2 seconds (~24/sec)
        -- confirmed live to be the direct cause of FYERS 429s, which in turn
        caused different symbols to randomly drop out of each scan."""
        async with self._throttle_lock:
            now = time.monotonic()
            while self._request_times and now - self._request_times[0] >= 1.0:
                self._request_times.popleft()
            if len(self._request_times) >= _MAX_REQUESTS_PER_SECOND:
                sleep_for = 1.0 - (now - self._request_times[0])
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                now = time.monotonic()
                while self._request_times and now - self._request_times[0] >= 1.0:
                    self._request_times.popleft()
            self._request_times.append(now)

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, FyersRateLimitError)),
    )
    async def _get(self, base_url: str, path: str, params: dict[str, Any] | None = None) -> dict:
        await self._throttle()
        url = f"{base_url}{path}"
        try:
            resp = await self._client.get(url, params=params, headers=self._auth_header())
        except httpx.TransportError as exc:
            logger.warning("FYERS network error on %s: %s", path, exc)
            raise
        return self._parse(resp, path)

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TransportError, FyersRateLimitError)),
    )
    async def _post(self, base_url: str, path: str, json: dict[str, Any]) -> dict:
        await self._throttle()
        url = f"{base_url}{path}"
        try:
            resp = await self._client.post(url, json=json, headers=self._auth_header())
        except httpx.TransportError as exc:
            logger.warning("FYERS network error on %s: %s", path, exc)
            raise
        return self._parse(resp, path)

    def _parse(self, resp: httpx.Response, path: str) -> dict:
        if resp.status_code == 429:
            logger.warning("FYERS rate limit hit on %s, retrying with backoff", path)
            raise FyersRateLimitError(f"Rate limited by FYERS on {path}", status_code=429)
        if resp.status_code >= 400:
            logger.error("FYERS API error on %s: HTTP %s", path, resp.status_code)
            raise FyersApiError(f"FYERS API error on {path}: HTTP {resp.status_code}", status_code=resp.status_code)
        data = resp.json()
        if data.get("s") not in ("ok", "success", None):
            logger.error("FYERS API returned error status on %s: %s", path, data.get("message"))
            raise FyersApiError(
                f"FYERS API returned error on {path}: {data.get('message', 'unknown')}",
                status_code=resp.status_code,
            )
        return data

    async def get_trading(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return await self._get(TRADING_BASE_URL, path, params)

    async def get_data(self, path: str, params: dict[str, Any] | None = None) -> dict:
        return await self._get(DATA_BASE_URL, path, params)

    async def post_trading(self, path: str, json: dict[str, Any]) -> dict:
        return await self._post(TRADING_BASE_URL, path, json)

    async def aclose(self) -> None:
        await self._client.aclose()
