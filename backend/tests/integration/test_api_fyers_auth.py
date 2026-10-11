"""/api/fyers/{login,callback,status,refresh}, the FYERS_AUTH_REQUIRED error
contract, and /api/health's FYERS component. FYERS itself is always mocked;
the session file is conftest's throwaway temp file."""

import base64
import json
import os
import time
import types
import urllib.parse
from pathlib import Path

import httpx
import pytest

import app.integrations.fyers.auth as auth_module
from app.config import Settings
from app.core.exceptions import FyersAuthRequiredError
from app.integrations.fyers.session import get_session_manager

pytestmark = pytest.mark.asyncio

SESSION_FILE = Path(os.environ["FYERS_SESSION_FILE"])  # conftest's temp file, never backend/.runtime/
assert ".runtime" not in str(SESSION_FILE)


def make_jwt(exp_offset_seconds: float, tag: str = "a") -> str:
    def b64(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64({'exp': time.time() + exp_offset_seconds, 'tag': tag})}.sig"


def fake_fyers_auth_http(monkeypatch, handler):
    real = httpx

    def _client(**kwargs):
        return real.AsyncClient(transport=real.MockTransport(handler))

    monkeypatch.setattr(auth_module, "httpx", types.SimpleNamespace(AsyncClient=_client, Response=real.Response))


@pytest.fixture
def live(monkeypatch):
    settings = Settings(
        use_mock_fyers=False,
        fyers_client_id="TEST-100",
        fyers_secret_key="test-secret",
        fyers_redirect_uri="http://127.0.0.1:8000/api/fyers/callback",
        fyers_access_token="",
    )
    import app.api.routes.fyers_auth as routes
    import app.api.routes.health as health
    import app.integrations.fyers.session as session

    for module in (routes, health, session):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    return settings


def _assert_no_secrets(text: str, *secrets: str) -> None:
    for secret in ("test-secret", *secrets):
        assert secret not in text


# ---- login ----------------------------------------------------------------------


async def test_login_mock_mode_is_409(app_client):
    resp = await app_client.get("/api/fyers/login", follow_redirects=False)
    assert resp.status_code == 409


async def test_login_redirects_to_fyers_with_state(app_client, live):
    resp = await app_client.get("/api/fyers/login", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://api-t1.fyers.in/api/v3/generate-authcode?")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
    assert query["client_id"] == ["TEST-100"]
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/api/fyers/callback"]
    assert len(query["state"][0]) > 20
    _assert_no_secrets(location)


# ---- callback -----------------------------------------------------------------


async def test_callback_rejects_unknown_state(app_client, live):
    resp = await app_client.get("/api/fyers/callback", params={"auth_code": "abc", "state": "forged"})
    assert resp.status_code == 400
    assert not SESSION_FILE.exists()


async def test_callback_stores_session_without_writing_env_or_leaking(app_client, live, monkeypatch):
    access, refresh = make_jwt(3600, "cb-access"), make_jwt(86400 * 15, "cb-refresh")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"s": "ok", "access_token": access, "refresh_token": refresh})

    fake_fyers_auth_http(monkeypatch, handler)

    login = await app_client.get("/api/fyers/login", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(login.headers["location"]).query)["state"][0]

    resp = await app_client.get("/api/fyers/callback", params={"auth_code": "one-time-code", "state": state})
    assert resp.status_code == 200
    assert "FYERS connected" in resp.text
    assert "http://localhost:8443/" in resp.text  # way back to the frontend
    _assert_no_secrets(resp.text, access, refresh)
    assert seen["body"] == {"grant_type": "authorization_code", "appIdHash": seen["body"]["appIdHash"], "code": "one-time-code"}

    stored = json.loads(SESSION_FILE.read_text())
    assert stored["access_token"] == access and stored["refresh_token"] == refresh

    # State is single-use.
    again = await app_client.get("/api/fyers/callback", params={"auth_code": "x", "state": state})
    assert again.status_code == 400

    status = (await app_client.get("/api/fyers/status")).json()
    assert status["status"] == "CONNECTED" and status["refresh_available"] is True


async def test_callback_exchange_failure_shows_error_page(app_client, live, monkeypatch):
    fake_fyers_auth_http(monkeypatch, lambda r: httpx.Response(400, json={"s": "error", "message": "invalid auth code"}))
    login = await app_client.get("/api/fyers/login", follow_redirects=False)
    state = urllib.parse.parse_qs(urllib.parse.urlparse(login.headers["location"]).query)["state"][0]
    resp = await app_client.get("/api/fyers/callback", params={"auth_code": "bad", "state": state})
    assert resp.status_code == 400
    assert "/api/fyers/login" in resp.text
    assert not SESSION_FILE.exists()


# ---- status ---------------------------------------------------------------------


async def test_status_mock(app_client):
    body = (await app_client.get("/api/fyers/status")).json()
    assert body["status"] == "MOCK" and body["mode"] == "mock"


async def test_status_login_required_when_no_session(app_client, live):
    body = (await app_client.get("/api/fyers/status")).json()
    assert body["status"] == "LOGIN_REQUIRED"
    assert body["authenticated"] is False
    assert body["login_url"] == "/api/fyers/login"


async def test_status_and_health_never_leak_tokens(app_client, live):
    access, refresh = make_jwt(3600, "leak-a"), make_jwt(86400, "leak-r")
    get_session_manager(live).store.save_tokens(access, refresh)
    status = await app_client.get("/api/fyers/status")
    health = await app_client.get("/api/health")
    for resp in (status, health):
        _assert_no_secrets(resp.text, access, refresh)
    assert status.json()["status"] == "CONNECTED"
    fyers = next(c for c in health.json()["components"] if c["name"] == "fyers")
    assert fyers == {"name": "fyers", "status": "ok", "detail": "CONNECTED"}


async def test_health_reports_login_required(app_client, live):
    fyers = next(c for c in (await app_client.get("/api/health")).json()["components"] if c["name"] == "fyers")
    assert fyers["status"] == "degraded" and fyers["detail"] == "LOGIN_REQUIRED"


# ---- refresh --------------------------------------------------------------------


async def test_refresh_rejects_bad_pin_without_echoing_it(app_client, live):
    resp = await app_client.post("/api/fyers/refresh", json={"pin": "12ab"})
    assert resp.status_code == 400
    assert "12ab" not in resp.text
    resp = await app_client.post("/api/fyers/refresh", content=b'"98765432"', headers={"Content-Type": "application/json"})
    assert resp.status_code == 400 and "98765432" not in resp.text


async def test_refresh_success_and_pin_not_echoed(app_client, live, monkeypatch):
    get_session_manager(live).store.save_tokens(make_jwt(-10), make_jwt(86400, "r"))
    new_access = make_jwt(3600, "refreshed")
    fake_fyers_auth_http(monkeypatch, lambda r: httpx.Response(200, json={"s": "ok", "access_token": new_access}))
    resp = await app_client.post("/api/fyers/refresh", json={"pin": "4821"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "CONNECTED"
    _assert_no_secrets(resp.text, "4821", new_access)


async def test_refresh_with_dead_refresh_token_requires_login(app_client, live, monkeypatch):
    get_session_manager(live).store.save_tokens(make_jwt(-10), make_jwt(86400, "r"))
    fake_fyers_auth_http(monkeypatch, lambda r: httpx.Response(401, json={"s": "error", "message": "token invalid"}))
    resp = await app_client.post("/api/fyers/refresh", json={"pin": "4821"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "FYERS_AUTH_REQUIRED"
    assert (await app_client.get("/api/fyers/status")).json()["status"] == "LOGIN_REQUIRED"


# ---- scanner surfaces FYERS_AUTH_REQUIRED -----------------------------------------


def _scan_body():
    return {"available_capital": 500000, "risk_percent": 1.0, "max_positions": 5, "holding_period": "1-4 weeks"}


async def test_scanner_returns_structured_auth_error(app_client, monkeypatch):
    import app.services.scanner_service as scanner_service

    async def _dead_session(client):
        raise FyersAuthRequiredError("FYERS session expired or invalid (HTTP 401 on /history)", status_code=401)

    monkeypatch.setattr(scanner_service, "get_nifty_candles", _dead_session)
    resp = await app_client.post("/api/scanner/run", json=_scan_body())
    assert resp.status_code == 401
    body = resp.json()
    assert body["code"] == "FYERS_AUTH_REQUIRED"
    assert body["login_url"] == "/api/fyers/login"


async def test_scanner_aborts_instead_of_partial_scan_on_auth_error(app_client, monkeypatch):
    import app.services.scanner_service as scanner_service

    async def _dead_session(*args, **kwargs):
        raise FyersAuthRequiredError("FYERS session expired", status_code=401)

    monkeypatch.setattr(scanner_service, "load_stock_context", _dead_session)
    resp = await app_client.post("/api/scanner/run", json=_scan_body())
    assert resp.status_code == 401
    assert resp.json()["code"] == "FYERS_AUTH_REQUIRED"
