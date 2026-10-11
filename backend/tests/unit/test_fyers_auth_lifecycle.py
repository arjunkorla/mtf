"""FYERS auth lifecycle: token store, session status, PIN refresh, 401
recovery, single-flight. All FYERS traffic goes through httpx.MockTransport
-- no real login, no real network. The session file is conftest's throwaway
TEST_FYERS_SESSION_FILE, never backend/.runtime/."""

import asyncio
import base64
import json
import logging
import os
import time
import types
from pathlib import Path

import httpx
import pytest

import app.integrations.fyers.auth as auth_module
from app.config import Settings
from app.core.exceptions import FyersAuthRequiredError
from app.integrations.fyers.auth import FyersPinRejected, FyersRefreshTokenInvalid
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.session import (
    CONNECTED,
    LOGIN_REQUIRED,
    MOCK,
    REFRESH_REQUIRED,
    get_session_manager,
)
from app.integrations.fyers.token_store import FyersTokenStore, get_token_store

TEST_FYERS_SESSION_FILE = Path(os.environ["FYERS_SESSION_FILE"])  # set by conftest to a temp dir
assert ".runtime" not in str(TEST_FYERS_SESSION_FILE)


def make_jwt(exp_offset_seconds: float, tag: str = "a") -> str:
    def b64(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64({'exp': time.time() + exp_offset_seconds, 'tag': tag})}.sig"


def live_settings(**overrides) -> Settings:
    base = dict(
        use_mock_fyers=False,
        fyers_client_id="TEST-100",
        fyers_secret_key="test-secret",
        fyers_redirect_uri="http://127.0.0.1:8000/api/fyers/callback",
        fyers_access_token="",
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    real_sleep = asyncio.sleep

    async def _fast_sleep(seconds):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", _fast_sleep)


def fake_fyers_auth_http(monkeypatch, handler):
    """Routes auth.py's httpx.AsyncClient through a MockTransport without
    patching the global httpx module."""
    real = httpx

    def _client(**kwargs):
        return real.AsyncClient(transport=real.MockTransport(handler))

    monkeypatch.setattr(auth_module, "httpx", types.SimpleNamespace(AsyncClient=_client, Response=real.Response))


def client_with(settings: Settings, handler) -> FyersClient:
    client = FyersClient(settings=settings)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


# ---- token store / status ----------------------------------------------------


def test_valid_access_token_is_connected():
    settings = live_settings()
    manager = get_session_manager(settings)
    manager.store.save_tokens(make_jwt(3600), make_jwt(86400, "r"))
    assert manager.status_code() == CONNECTED
    status = manager.status()
    assert status["authenticated"] is True
    assert status["refresh_available"] is True
    assert status["token_source"] == "session_store"


def test_expired_access_token_with_refresh_is_refresh_required():
    manager = get_session_manager(live_settings())
    manager.store.save_tokens(make_jwt(-10), make_jwt(86400, "r"))
    assert manager.store.is_access_token_valid() is False
    assert manager.status_code() == REFRESH_REQUIRED


def test_expired_access_token_without_refresh_is_login_required():
    manager = get_session_manager(live_settings())
    manager.store.save_tokens(make_jwt(-10))
    assert manager.status_code() == LOGIN_REQUIRED


def test_no_session_is_login_required_and_mock_is_mock():
    assert get_session_manager(live_settings()).status_code() == LOGIN_REQUIRED
    assert get_session_manager(Settings(use_mock_fyers=True)).status_code() == MOCK


def test_legacy_env_token_is_used_as_fallback():
    token = make_jwt(3600)
    manager = get_session_manager(live_settings(fyers_access_token=token))
    assert manager.store.token_source() == "env"
    assert manager.store.get_access_token() == token
    assert manager.status_code() == CONNECTED


def test_token_persistence_across_store_instances():
    access, refresh = make_jwt(3600), make_jwt(86400, "r")
    FyersTokenStore(TEST_FYERS_SESSION_FILE).save_tokens(access, refresh)
    reopened = FyersTokenStore(TEST_FYERS_SESSION_FILE)
    assert reopened.get_access_token() == access
    assert reopened.get_refresh_token() == refresh
    assert reopened.is_refresh_token_valid()
    reopened.clear_tokens()
    assert not TEST_FYERS_SESSION_FILE.exists()


def test_store_picks_up_external_file_change_without_restart():
    """The whole point of the store: a login written by another process
    (e.g. the callback) is visible without recreating anything."""
    store = get_token_store(live_settings())
    assert store.get_access_token() == ""
    new_token = make_jwt(3600, "external")
    FyersTokenStore(TEST_FYERS_SESSION_FILE).save_tokens(new_token)
    assert store.get_access_token() == new_token


def test_tokens_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    access, refresh = make_jwt(3600, "secretA"), make_jwt(86400, "secretR")
    store = FyersTokenStore(TEST_FYERS_SESSION_FILE)
    store.save_tokens(access, refresh)
    store.mark_access_token_rejected(access)
    assert access not in caplog.text and refresh not in caplog.text
    assert "***" in repr(auth_module.FyersTokens(access, refresh))
    assert access not in repr(auth_module.FyersTokens(access, refresh))


# ---- PIN refresh ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_refresh_stores_new_tokens(monkeypatch):
    settings = live_settings()
    manager = get_session_manager(settings)
    old_refresh = make_jwt(86400, "r-old")
    manager.store.save_tokens(make_jwt(-10), old_refresh)
    new_access, new_refresh = make_jwt(3600, "new"), make_jwt(86400 * 15, "r-new")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"s": "ok", "access_token": new_access, "refresh_token": new_refresh})

    fake_fyers_auth_http(monkeypatch, handler)
    status = await manager.refresh_with_pin("1234")

    assert seen["url"].endswith("/api/v3/validate-refresh-token")
    assert seen["body"]["grant_type"] == "refresh_token"
    assert seen["body"]["refresh_token"] == old_refresh
    assert seen["body"]["pin"] == "1234"
    assert len(seen["body"]["appIdHash"]) == 64
    assert status["status"] == CONNECTED
    assert manager.store.get_access_token() == new_access
    assert manager.store.get_refresh_token() == new_refresh
    assert "1234" not in TEST_FYERS_SESSION_FILE.read_text()  # PIN never persisted


@pytest.mark.asyncio
async def test_refresh_keeps_refresh_token_when_fyers_does_not_rotate_it(monkeypatch):
    manager = get_session_manager(live_settings())
    refresh = make_jwt(86400, "r")
    manager.store.save_tokens(make_jwt(-10), refresh)
    fake_fyers_auth_http(monkeypatch, lambda r: httpx.Response(200, json={"s": "ok", "access_token": make_jwt(3600)}))
    await manager.refresh_with_pin("1234")
    assert manager.store.get_refresh_token() == refresh


@pytest.mark.asyncio
async def test_failed_refresh_wrong_pin_keeps_refresh_token(monkeypatch):
    manager = get_session_manager(live_settings())
    manager.store.save_tokens(make_jwt(-10), make_jwt(86400, "r"))
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, json={"s": "error", "message": "Invalid pin"})

    fake_fyers_auth_http(monkeypatch, handler)
    with pytest.raises(FyersPinRejected):
        await manager.refresh_with_pin("0000")
    assert calls["n"] == 1  # never retried automatically
    assert manager.status_code() == REFRESH_REQUIRED


@pytest.mark.asyncio
async def test_rejected_refresh_token_transitions_to_login_required(monkeypatch):
    manager = get_session_manager(live_settings())
    manager.store.save_tokens(make_jwt(-10), make_jwt(86400, "r"))
    fake_fyers_auth_http(
        monkeypatch, lambda r: httpx.Response(401, json={"s": "error", "message": "Refresh token expired"})
    )
    with pytest.raises(FyersRefreshTokenInvalid):
        await manager.refresh_with_pin("1234")
    assert manager.status_code() == LOGIN_REQUIRED
    assert manager.store.get_refresh_token() == ""


@pytest.mark.asyncio
async def test_expired_refresh_token_makes_no_fyers_call(monkeypatch):
    manager = get_session_manager(live_settings())
    manager.store.save_tokens(make_jwt(-10), make_jwt(-5, "r"))  # refresh JWT already expired
    assert manager.status_code() == LOGIN_REQUIRED

    def handler(request):
        raise AssertionError("must not call FYERS with a known-expired refresh token")

    fake_fyers_auth_http(monkeypatch, handler)
    with pytest.raises(FyersRefreshTokenInvalid):
        await manager.refresh_with_pin("1234")


@pytest.mark.asyncio
async def test_concurrent_refresh_is_single_flight(monkeypatch):
    manager = get_session_manager(live_settings())
    manager.store.save_tokens(make_jwt(-10), make_jwt(86400, "r"))
    calls = {"n": 0}

    async def handler(request):
        calls["n"] += 1
        await asyncio.sleep(0)
        return httpx.Response(200, json={"s": "ok", "access_token": make_jwt(3600, "fresh")})

    fake_fyers_auth_http(monkeypatch, handler)
    results = await asyncio.gather(*(manager.refresh_with_pin("1234") for _ in range(10)))
    assert calls["n"] == 1
    assert all(r["status"] == CONNECTED for r in results)


# ---- 401 recovery -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_401_then_recovered_token_then_retry_succeeds():
    settings = live_settings()
    store = get_token_store(settings)
    old, new = make_jwt(3600, "old"), make_jwt(3600, "new")
    store.save_tokens(old)
    auth_headers = []

    def handler(request):
        header = request.headers["Authorization"]
        auth_headers.append(header)
        if header.endswith(old):
            # Simulates the session being renewed elsewhere (callback / PIN
            # refresh) while this request was in flight.
            FyersTokenStore(TEST_FYERS_SESSION_FILE).save_tokens(new)
            return httpx.Response(401, json={"s": "error", "message": "token expired"})
        return httpx.Response(200, json={"s": "ok", "candles": []})

    client = client_with(settings, handler)
    result = await client.get_data("/history", params={"symbol": "NSE:SBIN-EQ"})
    assert result == {"s": "ok", "candles": []}
    assert len(auth_headers) == 2  # original + exactly one retry
    assert auth_headers[1] == f"TEST-100:{new}"


@pytest.mark.asyncio
async def test_401_without_recovery_raises_auth_required_and_does_not_retry():
    settings = live_settings()
    manager = get_session_manager(settings)
    manager.store.save_tokens(make_jwt(3600, "revoked"), make_jwt(86400, "r"))
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(401, json={"s": "error", "message": "Could not authenticate"})

    client = client_with(settings, handler)
    with pytest.raises(FyersAuthRequiredError) as exc_info:
        await client.get_data("/history")
    assert exc_info.value.code == "FYERS_AUTH_REQUIRED"
    assert calls["n"] == 1
    assert manager.status_code() == REFRESH_REQUIRED  # token marked rejected; refresh token remains


@pytest.mark.asyncio
async def test_401_on_retry_raises_after_exactly_two_requests():
    settings = live_settings()
    store = get_token_store(settings)
    old, new = make_jwt(3600, "old"), make_jwt(3600, "new")
    store.save_tokens(old)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            FyersTokenStore(TEST_FYERS_SESSION_FILE).save_tokens(new)
        return httpx.Response(401, json={"s": "error"})

    client = client_with(settings, handler)
    with pytest.raises(FyersAuthRequiredError):
        await client.get_data("/history")
    assert calls["n"] == 2
    assert get_session_manager(settings).status_code() == LOGIN_REQUIRED


@pytest.mark.asyncio
async def test_concurrent_401s_do_not_storm(monkeypatch):
    settings = live_settings()
    get_token_store(settings).save_tokens(make_jwt(3600, "revoked"))
    calls = {"data": 0}

    def data_handler(request):
        calls["data"] += 1
        return httpx.Response(401, json={"s": "error"})

    def auth_handler(request):
        raise AssertionError("401 recovery must never call FYERS auth endpoints")

    fake_fyers_auth_http(monkeypatch, auth_handler)
    client = client_with(settings, data_handler)
    results = await asyncio.gather(*(client.get_data("/quotes") for _ in range(10)), return_exceptions=True)
    assert all(isinstance(r, FyersAuthRequiredError) for r in results)
    assert calls["data"] <= 10  # one request per caller, no retries against a dead token
    # After the first rejection, new requests fail fast locally -- zero FYERS calls.
    with pytest.raises(FyersAuthRequiredError):
        await client.get_data("/quotes")
    assert calls["data"] <= 10


@pytest.mark.asyncio
async def test_no_session_fails_fast_without_calling_fyers():
    settings = live_settings()

    def handler(request):
        raise AssertionError("must not call FYERS without a session")

    client = client_with(settings, handler)
    with pytest.raises(FyersAuthRequiredError):
        await client.get_data("/history")


@pytest.mark.asyncio
async def test_verify_is_cached(monkeypatch):
    settings = live_settings()
    manager = get_session_manager(settings)
    manager.store.save_tokens(make_jwt(3600))
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        assert request.url.path.endswith("/profile")
        return httpx.Response(200, json={"s": "ok", "data": {}})

    real_init = FyersClient.__init__

    def patched_init(self, settings=None, **kwargs):
        real_init(self, settings, **kwargs)
        self._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(FyersClient, "__init__", patched_init)
    first = await manager.verify()
    second = await manager.verify()
    assert first["verified"] is True and second["verified"] is True
    assert calls["n"] == 1
