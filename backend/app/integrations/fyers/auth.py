"""FYERS OAuth-style auth-code flow (mirrors fyers_apiv3.fyersModel.SessionModel)
plus the refresh-token exchange.

Flow:
  1. build_authcode_url() -> user opens this in a browser and logs in
  2. FYERS redirects to FYERS_REDIRECT_URI with `auth_code` in the query string
  3. exchange_auth_code(auth_code) -> POSTs to /validate-authcode, returns the
     access_token and (when FYERS issues one) the refresh_token
  4. refresh_access_token(refresh_token, pin) -> POSTs to
     /validate-refresh-token for a new access_token

Refresh-token contract (verified 2026-09-26): the installed SDK
(fyers-apiv3==3.1.18) exposes NO refresh helper -- SessionModel only has
generate_authcode()/generate_token(). The endpoint and payload below follow
FYERS' API v3 documentation as quoted by FYERS staff on the FYERS community:
POST {TRADING_BASE_URL}/validate-refresh-token with
{grant_type: "refresh_token", appIdHash, refresh_token, pin}; the refresh
token is valid for 15 days and the user's PIN is MANDATORY on every call.
Because the PIN must not be stored or auto-entered, refresh is only ever
performed with a PIN the user types in at that moment.

Neither function persists anything or logs token/PIN values -- persistence is
the token store's job (token_store.py).
"""

import hashlib
import urllib.parse
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import FyersAuthError
from app.integrations.fyers.fyers_client import TRADING_BASE_URL
from app.integrations.fyers.mock_responses import mock_token_response
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class FyersTokens:
    access_token: str
    refresh_token: str | None = None

    def __repr__(self) -> str:  # never let a token end up in a log line via repr()
        return f"FyersTokens(access_token=***, refresh_token={'***' if self.refresh_token else None})"


class FyersRefreshTokenInvalid(FyersAuthError):
    """FYERS rejected the refresh token itself (expired/invalid) -- a full
    interactive login is required."""


class FyersPinRejected(FyersAuthError):
    """FYERS rejected the refresh request and its message points at the PIN;
    the refresh token is kept so the user can try again."""


def build_authcode_url(settings: Settings | None = None, state: str = "mtf") -> str:
    settings = settings or get_settings()
    params = {
        "client_id": settings.fyers_client_id,
        "redirect_uri": settings.fyers_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{TRADING_BASE_URL}/generate-authcode?{urllib.parse.urlencode(params)}"


def _app_id_hash(settings: Settings) -> str:
    return hashlib.sha256(f"{settings.fyers_client_id}:{settings.fyers_secret_key}".encode()).hexdigest()


async def _post_auth(settings: Settings, category: str, url: str, payload: dict) -> httpx.Response:
    """Auth endpoints bypass FyersClient (no bearer token yet), but still
    count against the same FYERS request budget: recorded in the shared
    window at AUTH priority (never delayed) and metered. Never logs or
    meters the payload -- it carries the auth code / refresh token / PIN."""
    from app.integrations.fyers.request_control import (
        OUTCOME_HTTP_ERROR,
        OUTCOME_SUCCESS,
        OUTCOME_TRANSPORT_ERROR,
        RequestPriority,
        get_rate_limiter,
        record_request,
    )

    await get_rate_limiter().acquire(settings, RequestPriority.AUTH, category)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
    except httpx.TransportError:
        await record_request(category, OUTCOME_TRANSPORT_ERROR, RequestPriority.AUTH)
        raise
    await record_request(category, OUTCOME_SUCCESS if resp.status_code < 400 else OUTCOME_HTTP_ERROR, RequestPriority.AUTH)
    return resp


def _json_or_empty(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


async def exchange_auth_code(auth_code: str, settings: Settings | None = None) -> FyersTokens:
    """Exchanges a one-time auth_code for an access_token (+ refresh_token
    when FYERS returns one). Does not persist anything."""
    settings = settings or get_settings()

    if settings.use_mock_fyers:
        logger.info("Using mock FYERS token exchange (USE_MOCK_FYERS=true)")
        return FyersTokens(access_token=mock_token_response()["access_token"])

    if not settings.fyers_client_id or not settings.fyers_secret_key:
        raise FyersAuthError("FYERS_CLIENT_ID and FYERS_SECRET_KEY must be set to exchange an auth code")

    payload = {
        "grant_type": "authorization_code",
        "appIdHash": _app_id_hash(settings),
        "code": auth_code,
    }

    resp = await _post_auth(settings, "auth_code_exchange", f"{TRADING_BASE_URL}/validate-authcode", payload)

    data = _json_or_empty(resp)
    if resp.status_code >= 400 or data.get("s") != "ok" or not data.get("access_token"):
        logger.error("FYERS auth-code exchange failed: HTTP %s %s", resp.status_code, data.get("message", "unknown"))
        raise FyersAuthError(f"FYERS auth-code exchange failed: {data.get('message', 'unknown error')}")

    return FyersTokens(access_token=data["access_token"], refresh_token=data.get("refresh_token") or None)


async def refresh_access_token(refresh_token: str, pin: str, settings: Settings | None = None) -> FyersTokens:
    """ONE call to /validate-refresh-token. No retries -- repeated wrong-PIN
    attempts can lock the FYERS account, so the caller decides what next."""
    settings = settings or get_settings()

    if not settings.fyers_client_id or not settings.fyers_secret_key:
        raise FyersAuthError("FYERS_CLIENT_ID and FYERS_SECRET_KEY must be set to refresh a session")
    if not refresh_token:
        raise FyersRefreshTokenInvalid("No FYERS refresh token is stored -- a full FYERS login is required")

    payload = {
        "grant_type": "refresh_token",
        "appIdHash": _app_id_hash(settings),
        "refresh_token": refresh_token,
        "pin": pin,
    }

    resp = await _post_auth(settings, "auth_refresh", f"{TRADING_BASE_URL}/validate-refresh-token", payload)

    data = _json_or_empty(resp)
    if resp.status_code < 400 and data.get("s") == "ok" and data.get("access_token"):
        return FyersTokens(access_token=data["access_token"], refresh_token=data.get("refresh_token") or None)

    message = str(data.get("message") or f"HTTP {resp.status_code}")
    logger.error("FYERS refresh-token exchange failed: HTTP %s %s", resp.status_code, message)
    if "pin" in message.lower():
        raise FyersPinRejected(f"FYERS rejected the PIN: {message}")
    raise FyersRefreshTokenInvalid(f"FYERS refresh failed: {message}")
