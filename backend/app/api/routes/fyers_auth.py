"""FYERS session routes (local-dev auth lifecycle).

  GET  /api/fyers/login     302 -> FYERS authorization page (build_authcode_url)
  GET  /api/fyers/callback  FYERS redirects here; exchanges auth_code, stores the
                            session in the runtime token store, shows a small
                            page linking back to the frontend
  GET  /api/fyers/status    safe session status (never returns tokens/secrets);
                            ?verify=true makes ONE cached /profile call
  POST /api/fyers/refresh   {pin} -> ONE refresh-token exchange with a PIN the
                            user typed just now; the PIN is never stored/logged

Tokens never leave the backend. The callback no longer writes backend/.env --
that required recreating the api container (docker env_file snapshot) before
the new token took effect; the token store is read live instead.
"""

import html
import re
import secrets
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import get_settings
from app.core.exceptions import FyersAuthError
from app.integrations.fyers.auth import FyersPinRejected, FyersRefreshTokenInvalid, build_authcode_url
from app.integrations.fyers.session import get_session_manager
from app.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()

# OAuth `state` values issued by /login (CSRF protection for the callback).
# In-memory is enough for a single-process local app; if the backend reloads
# mid-login the user simply starts the login again.
_STATE_TTL_SECONDS = 600
_pending_states: dict[str, float] = {}

_PIN_RE = re.compile(r"^\d{4,6}$")


def _issue_state() -> str:
    now = time.time()
    for s, issued in list(_pending_states.items()):
        if now - issued > _STATE_TTL_SECONDS:
            _pending_states.pop(s, None)
    state = secrets.token_urlsafe(24)
    _pending_states[state] = now
    return state


def _consume_state(state: str | None) -> bool:
    if not state:
        return False
    issued = _pending_states.pop(state, None)
    return issued is not None and time.time() - issued <= _STATE_TTL_SECONDS


def _page(title: str, message: str, ok: bool) -> HTMLResponse:
    frontend = html.escape(get_settings().frontend_url, quote=True)
    colour = "#22C9B4" if ok else "#F05252"
    auto = f'<meta http-equiv="refresh" content="3;url={frontend}">' if ok else ""
    retry = "" if ok else '<p><a href="/api/fyers/login">Try FYERS login again</a></p>'
    body = f"""<!doctype html><html><head><meta charset="utf-8">{auto}<title>{html.escape(title)}</title>
<style>body{{background:#080B10;color:#E2E8F0;font-family:system-ui,sans-serif;display:flex;
justify-content:center;padding-top:15vh}}.c{{max-width:28rem;border:1px solid #1A2540;border-radius:8px;
padding:24px;background:#0F1520}}h1{{font-size:18px;color:{colour}}}a{{color:#CF8B2E}}</style></head>
<body><div class="c"><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{retry}
<p><a href="{frontend}">Return to MTF Scanner</a></p></div></body></html>"""
    return HTMLResponse(body, status_code=200 if ok else 400)


@router.get("/fyers/login", response_model=None)
async def fyers_login() -> RedirectResponse | JSONResponse:
    settings = get_settings()
    if settings.use_mock_fyers:
        return JSONResponse(status_code=409, content={"detail": "USE_MOCK_FYERS=true -- FYERS login is not used in mock mode."})
    if not settings.fyers_client_id or not settings.fyers_secret_key or not settings.fyers_redirect_uri:
        return JSONResponse(
            status_code=500,
            content={"detail": "FYERS_CLIENT_ID, FYERS_SECRET_KEY and FYERS_REDIRECT_URI must be configured in backend/.env."},
        )
    return RedirectResponse(build_authcode_url(settings, state=_issue_state()), status_code=302)


@router.get("/fyers/callback", response_class=HTMLResponse)
async def fyers_callback(
    auth_code: str | None = Query(None),
    state: str | None = None,
    s: str | None = None,
    message: str | None = None,
) -> HTMLResponse:
    if not auth_code:
        detail = message or "FYERS did not return an authorization code."
        return _page("FYERS login failed", detail, ok=False)
    if not _consume_state(state):
        return _page(
            "FYERS login link expired",
            "This login response doesn't match a login started from this app (or it is older than 10 minutes). "
            "Start the FYERS login again.",
            ok=False,
        )
    try:
        status = await get_session_manager().complete_login(auth_code)
    except FyersAuthError as exc:
        return _page("FYERS login failed", str(exc), ok=False)

    refresh_note = (
        " A refresh token was stored, so for the next 15 days you can reconnect with just your PIN."
        if status["refresh_available"] else ""
    )
    return _page("FYERS connected", "Session stored on the backend." + refresh_note + " Returning to the scanner…", ok=True)


@router.get("/fyers/status")
async def fyers_status(verify: bool = Query(False)) -> dict:
    manager = get_session_manager()
    if verify:
        return await manager.verify()
    return manager.status()


@router.post("/fyers/refresh", response_model=None)
async def fyers_refresh(request: Request) -> dict | JSONResponse:
    # Parsed by hand (not a Pydantic body) so a malformed request can never
    # echo the PIN back inside a 422 validation-error body.
    settings = get_settings()
    if settings.use_mock_fyers:
        return JSONResponse(status_code=409, content={"detail": "USE_MOCK_FYERS=true -- nothing to refresh."})
    try:
        body = await request.json()
    except ValueError:
        body = None
    pin = body.get("pin") if isinstance(body, dict) else None
    if not isinstance(pin, str) or not _PIN_RE.match(pin):
        return JSONResponse(status_code=400, content={"detail": "Enter your FYERS PIN (digits only)."})

    manager = get_session_manager()
    try:
        return await manager.refresh_with_pin(pin)
    except FyersPinRejected:
        return JSONResponse(
            status_code=400,
            content={"detail": "FYERS rejected the PIN. Check it before trying again -- repeated wrong PINs can lock your FYERS account.",
                     "code": "FYERS_PIN_REJECTED"},
        )
    except FyersRefreshTokenInvalid:
        return JSONResponse(
            status_code=401,
            content={"detail": "FYERS refresh token expired or invalid -- a full FYERS login is required.",
                     "code": "FYERS_AUTH_REQUIRED", "fyers_status": manager.status_code(), "login_url": "/api/fyers/login"},
        )
    except FyersAuthError as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
