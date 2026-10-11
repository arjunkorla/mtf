"""Runtime FYERS session store -- separate from static configuration.

Static configuration (FYERS_CLIENT_ID / FYERS_SECRET_KEY / FYERS_REDIRECT_URI)
stays in Settings/.env. The mutable session (access_token, refresh_token,
expiry metadata) lives here instead, in a small JSON file under
backend/.runtime/ (gitignored + dockerignored).

Why a file and not .env: docker-compose's `env_file` snapshots .env into the
container's OS environment at creation time, and pydantic-settings gives OS
env vars priority over the .env file -- so rewriting .env from the OAuth
callback could never reach the running process without recreating the
container. backend/ is bind-mounted into the container (.:/app), so this file
is shared by host and container and survives container recreation, and it is
re-read whenever its mtime changes, so every consumer sees the CURRENT token.

Legacy fallback: if the store holds no access token, FYERS_ACCESS_TOKEN from
Settings is used (so an existing .env token keeps working), unless that exact
token has already been rejected by FYERS with a 401.

Never logs or returns token values.
"""

import base64
import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.config import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# app/integrations/fyers/token_store.py -> parents[3] is backend/ (== /app in the container)
_BACKEND_DIR = Path(__file__).resolve().parents[3]
DEFAULT_SESSION_FILE = _BACKEND_DIR / ".runtime" / "fyers_session.json"

# FYERS documents a 15-day refresh-token validity. Only used when the refresh
# token isn't a decodable JWT carrying its own `exp`.
REFRESH_TOKEN_FALLBACK_TTL_SECONDS = 15 * 24 * 3600

# Treat a token as expired slightly early so a request doesn't race the expiry.
_EXPIRY_SKEW_SECONDS = 60


def token_fingerprint(token: str) -> str:
    """Short one-way identifier for a token -- lets us remember WHICH token
    was rejected without persisting or logging the token itself twice."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def jwt_expiry(token: str) -> float | None:
    """Reads the `exp` claim of a JWT WITHOUT verifying it (we only need the
    advisory expiry to avoid pointless calls; FYERS remains the authority via
    its 401s). Returns None when the token isn't a decodable JWT."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload_b64)).get("exp")
        return float(exp) if exp is not None else None
    except (IndexError, ValueError, TypeError, AttributeError):
        return None


@dataclass
class FyersSession:
    access_token: str = ""
    refresh_token: str = ""
    access_expires_at: float | None = None
    refresh_expires_at: float | None = None
    obtained_at: float | None = None
    refreshed_at: float | None = None
    rejected_access_fingerprint: str | None = None


class FyersTokenStore:
    def __init__(self, path: Path, fallback_access_token: str = ""):
        self.path = path
        self._fallback_access_token = fallback_access_token
        self._lock = threading.Lock()  # guards file I/O; used from asyncio code AND the WebSocket thread
        self._cached: FyersSession | None = None
        self._cached_mtime: tuple | None = None  # (mtime_ns, size, inode) of the file last read

    @staticmethod
    def _signature(st: os.stat_result) -> tuple:
        # os.replace() gives every write a new inode, so this detects external
        # writes even where mtime resolution is coarse (Docker bind mounts).
        return (st.st_mtime_ns, st.st_size, st.st_ino)

    # ---- persistence -------------------------------------------------------

    def _load(self) -> FyersSession:
        with self._lock:
            try:
                mtime = self._signature(self.path.stat())
            except FileNotFoundError:
                self._cached, self._cached_mtime = FyersSession(), None
                return self._cached
            if self._cached is not None and self._cached_mtime == mtime:
                return self._cached
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                known = FyersSession.__dataclass_fields__.keys()
                session = FyersSession(**{k: v for k, v in raw.items() if k in known})
            except (OSError, ValueError, TypeError):
                logger.error("FYERS session file is unreadable/corrupt; treating the session as empty")
                session = FyersSession()
            self._cached, self._cached_mtime = session, mtime
            return session

    def _write(self, session: FyersSession) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(session)), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)  # best-effort; a no-op on Windows bind mounts
            except OSError:
                pass
            os.replace(tmp, self.path)
            self._cached = session
            self._cached_mtime = self._signature(self.path.stat())

    # ---- public API --------------------------------------------------------

    def session(self) -> FyersSession:
        return self._load()

    def token_source(self) -> str:
        if self._load().access_token:
            return "session_store"
        if self._fallback_access_token:
            return "env"
        return "none"

    def get_access_token(self) -> str:
        """The current access token, or "" if none/known-rejected."""
        session = self._load()
        token = session.access_token or self._fallback_access_token
        if token and session.rejected_access_fingerprint == token_fingerprint(token):
            return ""
        return token

    def get_refresh_token(self) -> str:
        return self._load().refresh_token

    def access_expires_at(self) -> float | None:
        session = self._load()
        if session.access_token:
            return session.access_expires_at
        return jwt_expiry(self._fallback_access_token) if self._fallback_access_token else None

    def is_access_token_valid(self, now: float | None = None) -> bool:
        """Locally decidable validity only (present, not rejected, not past
        its JWT expiry). Does NOT call FYERS."""
        if not self.get_access_token():
            return False
        exp = self.access_expires_at()
        now = time.time() if now is None else now
        return exp is None or now < exp - _EXPIRY_SKEW_SECONDS

    def is_refresh_token_valid(self, now: float | None = None) -> bool:
        session = self._load()
        if not session.refresh_token:
            return False
        now = time.time() if now is None else now
        return session.refresh_expires_at is None or now < session.refresh_expires_at - _EXPIRY_SKEW_SECONDS

    def save_tokens(self, access_token: str, refresh_token: str | None = None, *, is_refresh: bool = False) -> None:
        """Persists a newly issued access token. A refresh token is only
        replaced when FYERS actually returned one; otherwise the existing one
        is kept (a refresh call may not rotate it)."""
        current = self._load()
        now = time.time()
        new_refresh = refresh_token if refresh_token else (current.refresh_token if is_refresh else "")
        if refresh_token:
            refresh_exp = jwt_expiry(refresh_token) or now + REFRESH_TOKEN_FALLBACK_TTL_SECONDS
        elif is_refresh:
            refresh_exp = current.refresh_expires_at
        else:
            refresh_exp = None
        self._write(
            FyersSession(
                access_token=access_token,
                refresh_token=new_refresh,
                access_expires_at=jwt_expiry(access_token),
                refresh_expires_at=refresh_exp,
                obtained_at=current.obtained_at if is_refresh else now,
                refreshed_at=now if is_refresh else None,
                rejected_access_fingerprint=None,
            )
        )
        logger.info("FYERS session stored (refresh_token %s)", "present" if new_refresh else "absent")

    def mark_access_token_rejected(self, token: str) -> None:
        """Records that FYERS answered 401 for `token`, so status reporting
        and later requests stop treating it as usable."""
        session = self._load()
        session = FyersSession(**{**asdict(session), "rejected_access_fingerprint": token_fingerprint(token)})
        self._write(session)
        logger.warning("FYERS access token rejected (401); session marked invalid")

    def clear_refresh_token(self) -> None:
        session = self._load()
        self._write(FyersSession(**{**asdict(session), "refresh_token": "", "refresh_expires_at": None}))

    def clear_tokens(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)
            self._cached, self._cached_mtime = None, None


_stores: dict[str, FyersTokenStore] = {}
_stores_lock = threading.Lock()


def get_token_store(settings: Settings | None = None) -> FyersTokenStore:
    settings = settings or get_settings()
    path = Path(settings.fyers_session_file) if settings.fyers_session_file else DEFAULT_SESSION_FILE
    key = f"{path}|{token_fingerprint(settings.fyers_access_token) if settings.fyers_access_token else ''}"
    with _stores_lock:
        store = _stores.get(key)
        if store is None:
            store = FyersTokenStore(path, fallback_access_token=settings.fyers_access_token)
            _stores[key] = store
        return store
