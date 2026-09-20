"""FYERS OAuth-style auth-code flow (mirrors fyers_apiv3.fyersModel.SessionModel).

Flow:
  1. build_authcode_url() -> user opens this in a browser and logs in
  2. FYERS redirects to FYERS_REDIRECT_URI with `auth_code` in the query string
  3. exchange_auth_code(auth_code) -> POSTs to /validate-authcode, returns access_token

The resulting access_token must be stored as FYERS_ACCESS_TOKEN (env var /
secret store) -- this module never persists it to the database or returns it
to the frontend.
"""

import hashlib
import urllib.parse

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import FyersAuthError
from app.integrations.fyers.fyers_client import TRADING_BASE_URL
from app.integrations.fyers.mock_responses import mock_token_response
from app.logging_config import get_logger

logger = get_logger(__name__)


def build_authcode_url(settings: Settings | None = None, state: str = "mtf") -> str:
    settings = settings or get_settings()
    params = {
        "client_id": settings.fyers_client_id,
        "redirect_uri": settings.fyers_redirect_uri,
        "response_type": "code",
        "state": state,
    }
    return f"{TRADING_BASE_URL}/generate-authcode?{urllib.parse.urlencode(params)}"


async def exchange_auth_code(auth_code: str, settings: Settings | None = None) -> str:
    """Exchanges a one-time auth_code for an access_token.

    Returns the access_token string. Caller is responsible for persisting it
    (e.g. updating the deployment's secret store) -- this function does not
    write to the database.
    """
    settings = settings or get_settings()

    if settings.use_mock_fyers:
        logger.info("Using mock FYERS token exchange (USE_MOCK_FYERS=true)")
        return mock_token_response()["access_token"]

    if not settings.fyers_client_id or not settings.fyers_secret_key:
        raise FyersAuthError("FYERS_CLIENT_ID and FYERS_SECRET_KEY must be set to exchange an auth code")

    app_id_hash = hashlib.sha256(
        f"{settings.fyers_client_id}:{settings.fyers_secret_key}".encode()
    ).hexdigest()

    payload = {
        "grant_type": "authorization_code",
        "appIdHash": app_id_hash,
        "code": auth_code,
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{TRADING_BASE_URL}/validate-authcode", json=payload)

    data = resp.json()
    if resp.status_code >= 400 or data.get("s") != "ok":
        logger.error("FYERS auth-code exchange failed: %s", data.get("message", "unknown"))
        raise FyersAuthError(f"FYERS auth-code exchange failed: {data.get('message', 'unknown error')}")

    return data["access_token"]
