"""Low-level async HTTP client for FYERS API v3.

Mirrors the REST surface of the official `fyers-apiv3` Python SDK
(https://myapi.fyers.in/docsv3): base URL https://api-t1.fyers.in/api/v3 for
trading/account endpoints, https://api-t1.fyers.in/data for market-data
endpoints. Static credentials come from Settings (env vars); the live access
token comes from the runtime session store (token_store.py) on every request.
Never hard-coded, never echoed to the frontend.

When settings.use_mock_fyers is true, calls short-circuit to canned payloads
from mock_responses.py so the rest of the pipeline is testable without a live
FYERS account.
"""

from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings, get_settings
from app.core.exceptions import FyersApiError, FyersAuthError, FyersLocalCapacityExceeded, FyersRateLimitError
from app.integrations.fyers.request_control import (
    OUTCOME_API_ERROR,
    OUTCOME_HTTP_ERROR,
    OUTCOME_RATE_LIMITED,
    OUTCOME_SUCCESS,
    OUTCOME_TRANSPORT_ERROR,
    OUTCOME_UNAUTHORIZED,
    RequestPriority,
    categorize_path,
    current_priority,
    get_rate_limiter,
    record_request,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

TRADING_BASE_URL = "https://api-t1.fyers.in/api/v3"
DATA_BASE_URL = "https://api-t1.fyers.in/data"

# Confirmed live cap: 10 req/sec, 200/min, 100,000/day -- breaching the
# per-minute cap 3x in a day gets the whole account blocked for the rest of
# the day. Enforced by the PROCESS-WIDE, Redis-coordinated limiter in
# request_control.py (Phase 0) -- this used to be a per-instance 8/sec
# throttle here, which let concurrent clients (a fresh one per scanner run /
# request) each spend their own budget and never enforced the per-minute cap.


def _is_retryable(exc: BaseException) -> bool:
    # Our own limiter refusing a request must not be retried: the retry
    # would just queue behind the same exhausted budget.
    if isinstance(exc, FyersLocalCapacityExceeded):
        return False
    return isinstance(exc, (httpx.TransportError, FyersRateLimitError))


class FyersClient:
    """Thin async wrapper around FYERS v3 REST endpoints.

    All higher-level adapters (quotes.py, historical_data.py, fno.py,
    market_data.py) go through this client so retry, auth-header, rate
    limiting, metering and error-normalization logic lives in exactly one
    place.

    `priority` defaults to the ambient request_control.fyers_priority()
    context (INTERACTIVE when none is set).
    """

    def __init__(self, settings: Settings | None = None, priority: RequestPriority | None = None):
        self.settings = settings or get_settings()
        self._client = httpx.AsyncClient(timeout=10.0)
        self._priority = priority

    @property
    def use_mock(self) -> bool:
        return self.settings.use_mock_fyers

    @property
    def _session(self):
        # Lazy import: session.py -> auth.py -> this module (TRADING_BASE_URL).
        from app.integrations.fyers.session import get_session_manager

        return get_session_manager(self.settings)

    def _current_token(self) -> str:
        """The CURRENT runtime token from the session store (not a value
        snapshotted at startup), so a fresh OAuth login is picked up by the
        next request without restarting anything."""
        if not self.settings.fyers_client_id:
            raise FyersAuthError(
                "FYERS credentials missing: set FYERS_CLIENT_ID, or enable USE_MOCK_FYERS=true for local development."
            )
        token = self._session.store.get_access_token()
        if not token:
            raise self._session.auth_required_error("(no stored session)")
        return token

    def _auth_header(self, token: str) -> dict[str, str]:
        return {"Authorization": f"{self.settings.fyers_client_id}:{token}"}

    @property
    def priority(self) -> RequestPriority:
        return self._priority or current_priority()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception(_is_retryable),
    )
    async def _attempt(
        self, method: str, base_url: str, path: str, token: str,
        params: dict[str, Any] | None = None, json: dict[str, Any] | None = None,
    ) -> dict | None:
        """One logical request (transport errors/429s retried with backoff).
        Returns None on HTTP 401 so _send() can run auth recovery -- a 401 is
        never retried here. Every attempt (including retries) must first be
        admitted by the shared limiter, and its outcome is metered."""
        category = categorize_path(path)
        priority = self.priority
        await get_rate_limiter().acquire(self.settings, priority, category)
        url = f"{base_url}{path}"
        try:
            resp = await self._client.request(method, url, params=params, json=json, headers=self._auth_header(token))
        except httpx.TransportError as exc:
            logger.warning("FYERS network error on %s: %s", path, exc)
            await record_request(category, OUTCOME_TRANSPORT_ERROR, priority)
            raise
        if resp.status_code == 401:
            logger.warning("FYERS rejected the session on %s: HTTP 401", path)
            await record_request(category, OUTCOME_UNAUTHORIZED, priority)
            return None
        if resp.status_code == 429:
            await record_request(category, OUTCOME_RATE_LIMITED, priority)
            await get_rate_limiter().note_provider_429(self.settings)
            return self._parse(resp, path)  # raises FyersRateLimitError -> retried with backoff
        try:
            data = self._parse(resp, path)
        except FyersApiError:
            await record_request(category, OUTCOME_HTTP_ERROR if resp.status_code >= 400 else OUTCOME_API_ERROR, priority)
            raise
        await record_request(category, OUTCOME_SUCCESS, priority)
        return data

    async def _send(
        self, method: str, base_url: str, path: str,
        params: dict[str, Any] | None = None, json: dict[str, Any] | None = None,
    ) -> dict:
        """Centralized 401 handling: at most ONE recovery (single-flight, see
        session.py) and ONE retry of the original request, then a structured
        FyersAuthRequiredError -- never an endless loop, never mock data."""
        token = self._current_token()
        data = await self._attempt(method, base_url, path, token, params, json)
        if data is not None:
            return data

        new_token = await self._session.recover_from_unauthorized(token)
        if new_token is None:
            raise self._session.auth_required_error(path)

        data = await self._attempt(method, base_url, path, new_token, params, json)
        if data is not None:
            return data
        await self._session.recover_from_unauthorized(new_token)  # marks it rejected too
        raise self._session.auth_required_error(path)

    async def _get(self, base_url: str, path: str, params: dict[str, Any] | None = None) -> dict:
        return await self._send("GET", base_url, path, params=params)

    async def _post(self, base_url: str, path: str, json: dict[str, Any]) -> dict:
        return await self._send("POST", base_url, path, json=json)

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
