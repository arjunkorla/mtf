"""FYERS session lifecycle: status, 401 recovery, login completion, PIN refresh.

Single place that decides whether the app can talk to FYERS right now.

Status values:
  CONNECTED         a usable access token is stored (locally valid; see
                    `verified` for whether FYERS itself confirmed it)
  REFRESH_REQUIRED  access token missing/expired/rejected, but a refresh
                    token is stored -- the user can reconnect with their PIN
  LOGIN_REQUIRED    nothing recoverable -- full FYERS login required
  MOCK              USE_MOCK_FYERS=true
  ERROR             static FYERS configuration is missing

Rate-limit safety: every recovery/refresh path runs under one asyncio lock
(single-flight). N concurrent requests hitting 401 with the same token
produce at most one state transition and ZERO extra FYERS auth calls; a
request whose token was already replaced by someone else just picks up the
new token and retries once.

Why 401 recovery never refreshes on its own: FYERS requires the user's PIN
for every refresh (see auth.py). The PIN is never stored, so automatic
recovery can only reuse a token another request / the login callback / a
PIN refresh has already stored; otherwise it fails fast with
FyersAuthRequiredError.
"""

import asyncio
import datetime as dt
import time

from app.config import Settings, get_settings
from app.core.exceptions import FyersAuthError, FyersAuthRequiredError
from app.integrations.fyers.token_store import FyersTokenStore, get_token_store
from app.logging_config import get_logger

logger = get_logger(__name__)

CONNECTED = "CONNECTED"
REFRESH_REQUIRED = "REFRESH_REQUIRED"
LOGIN_REQUIRED = "LOGIN_REQUIRED"
MOCK = "MOCK"
ERROR = "ERROR"

LOGIN_PATH = "/api/fyers/login"
VERIFY_CACHE_SECONDS = 60.0

_STATUS_MESSAGES = {
    CONNECTED: "FYERS session active.",
    REFRESH_REQUIRED: "FYERS session expired. Reconnect with your FYERS PIN, or log in again.",
    LOGIN_REQUIRED: "FYERS login required.",
    MOCK: "Mock FYERS mode (USE_MOCK_FYERS=true) -- no live data.",
    ERROR: "FYERS is not configured (FYERS_CLIENT_ID / FYERS_SECRET_KEY / FYERS_REDIRECT_URI).",
}


def _iso(ts: float | None) -> str | None:
    return dt.datetime.fromtimestamp(ts, dt.UTC).isoformat() if ts else None


class FyersSessionManager:
    def __init__(self, settings: Settings, store: FyersTokenStore):
        self.settings = settings
        self.store = store
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        self._verified_at: float | None = None
        self._verified_token_fp: str | None = None
        self._verification_error: str | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock, self._lock_loop = asyncio.Lock(), loop
        return self._lock

    # ---- status (no network) ----------------------------------------------

    def status_code(self) -> str:
        s = self.settings
        if s.use_mock_fyers:
            return MOCK
        if not s.fyers_client_id or not s.fyers_secret_key:
            return ERROR
        if self.store.is_access_token_valid():
            return CONNECTED
        if self.store.is_refresh_token_valid():
            return REFRESH_REQUIRED
        return LOGIN_REQUIRED

    def status(self) -> dict:
        """Safe-to-return status. Contains NO token, secret, or PIN."""
        from app.integrations.fyers.token_store import token_fingerprint

        code = self.status_code()
        session = self.store.session()
        current = self.store.get_access_token()
        verified = (
            code == CONNECTED
            and self._verified_at is not None
            and current != ""
            and self._verified_token_fp == token_fingerprint(current)
        )
        return {
            "mode": "mock" if self.settings.use_mock_fyers else "live",
            "status": code,
            "authenticated": code in (CONNECTED, MOCK),
            "refresh_available": code != MOCK and self.store.is_refresh_token_valid(),
            "refresh_requires_pin": True,
            "verified": verified,
            "last_verified_at": _iso(self._verified_at) if verified else None,
            "verification_error": self._verification_error,
            "access_expires_at": _iso(self.store.access_expires_at()) if code != MOCK else None,
            "refresh_expires_at": _iso(session.refresh_expires_at) if code != MOCK else None,
            "token_source": self.store.token_source() if code != MOCK else "mock",
            "login_url": LOGIN_PATH,
            "message": _STATUS_MESSAGES[code],
        }

    # ---- 401 recovery -------------------------------------------------------

    async def recover_from_unauthorized(self, failed_token: str) -> str | None:
        """Called by FyersClient after an HTTP 401. Returns a DIFFERENT, usable
        token to retry with exactly once, or None when the user must
        reconnect (the failed token is then marked rejected)."""
        async with self._get_lock():
            current = self.store.get_access_token()
            if current and current != failed_token and self.store.is_access_token_valid():
                logger.info("FYERS 401 recovered: a newer session token is already stored; retrying once")
                return current
            if current == failed_token:
                self.store.mark_access_token_rejected(failed_token)
                self._verified_at = None
            return None

    def auth_required_error(self, path: str) -> FyersAuthRequiredError:
        code = self.status_code()
        hint = "reconnect with your FYERS PIN or log in again" if code == REFRESH_REQUIRED else "log in to FYERS again"
        return FyersAuthRequiredError(f"FYERS session expired or invalid (HTTP 401 on {path}); {hint}.", status_code=401)

    # ---- login / refresh ----------------------------------------------------

    async def complete_login(self, auth_code: str) -> dict:
        from app.integrations.fyers.auth import exchange_auth_code

        async with self._get_lock():
            tokens = await exchange_auth_code(auth_code, self.settings)
            if not self.settings.use_mock_fyers:
                self.store.save_tokens(tokens.access_token, tokens.refresh_token)
            self._verified_at = None
            self._verification_error = None
        return self.status()

    async def refresh_with_pin(self, pin: str) -> dict:
        """ONE refresh attempt with a PIN the user just typed. Single-flight:
        if another caller already restored the session while we waited, no
        FYERS call is made."""
        from app.integrations.fyers.auth import FyersRefreshTokenInvalid, refresh_access_token

        async with self._get_lock():
            if self.store.is_access_token_valid():
                return self.status()
            if not self.store.is_refresh_token_valid():
                raise FyersRefreshTokenInvalid("No valid FYERS refresh token -- a full FYERS login is required")
            try:
                tokens = await refresh_access_token(self.store.get_refresh_token(), pin, self.settings)
            except FyersRefreshTokenInvalid:
                self.store.clear_refresh_token()  # -> LOGIN_REQUIRED, never retried
                raise
            self.store.save_tokens(tokens.access_token, tokens.refresh_token, is_refresh=True)
            self._verified_at = None
            self._verification_error = None
        return self.status()

    # ---- verification (one cheap real call, cached) --------------------------

    async def verify(self, force: bool = False) -> dict:
        """Confirms a locally-valid token with ONE /profile call, cached for
        VERIFY_CACHE_SECONDS so polling can't multiply FYERS requests."""
        from app.integrations.fyers.fyers_client import FyersClient
        from app.integrations.fyers.token_store import token_fingerprint

        if self.status_code() != CONNECTED:
            return self.status()
        current_fp = token_fingerprint(self.store.get_access_token())
        fresh = (
            self._verified_at is not None
            and self._verified_token_fp == current_fp
            and time.time() - self._verified_at < VERIFY_CACHE_SECONDS
        )
        if fresh and not force:
            return self.status()

        from app.integrations.fyers.request_control import RequestPriority

        # AUTH tier: recorded in the shared window but never delayed by
        # market-data traffic (see request_control.py).
        client = FyersClient(settings=self.settings, priority=RequestPriority.AUTH)
        try:
            await client.get_trading("/profile")
            self._verified_at, self._verified_token_fp = time.time(), current_fp
            self._verification_error = None
        except FyersAuthRequiredError:
            self._verified_at = None
            self._verification_error = None  # status itself now says REFRESH/LOGIN_REQUIRED
        except FyersAuthError as exc:
            self._verification_error = str(exc)[:200]
        except Exception as exc:  # noqa: BLE001 -- network/5xx: report, don't change auth state
            self._verification_error = f"Could not reach FYERS to verify the session: {type(exc).__name__}"
        finally:
            await client.aclose()
        return self.status()


# Keyed by Settings identity: production uses the one lru_cache'd Settings,
# so every FyersClient shares one manager (and therefore one lock).
_managers: dict[int, FyersSessionManager] = {}


def get_session_manager(settings: Settings | None = None) -> FyersSessionManager:
    settings = settings or get_settings()
    manager = _managers.get(id(settings))
    if manager is None or manager.settings is not settings:
        manager = FyersSessionManager(settings, get_token_store(settings))
        _managers[id(settings)] = manager
    return manager


def reset_session_managers() -> None:
    """Test helper."""
    _managers.clear()
