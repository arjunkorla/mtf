"""Tests for FyersMarketDataSocket's LIVE (non-mock) code path -- the
lifecycle-correctness fix from the 2026-09-20 audit (stop() must actually
close the underlying FYERS SDK connection, not just our own polling
thread), plus the singleton-ownership guard.

Uses a fake stand-in for fyers_apiv3.FyersWebsocket.data_ws.FyersDataSocket
that mirrors the REAL installed SDK's verified behavior (confirmed via
`inspect.getsource` against fyers-apiv3==3.1.18, 2026-09-20):
  - __new__ singleton via a class-level _instance
  - connect() invokes on_connect synchronously
  - close_connection() sets restart_flag=False, flips is_connected() to
    False, and fires on_close() -- exactly the real method's documented
    behavior, not a broader mock of the whole SDK.
This keeps the test suite network-free while proving OUR wrapper code
actually calls the real shutdown method with the right effects, rather than
re-testing the vendor SDK itself.
"""

import sys
import time
import types

import pytest

import app.integrations.fyers.websocket as ws_module
from app.config import Settings
from app.integrations.fyers.websocket import FyersMarketDataSocket


class _FakeSDKSocket:
    """Singleton stand-in for data_ws.FyersDataSocket, matching the real
    class's verified __new__/close_connection/is_connected semantics."""

    _instance = None
    close_connection_calls = 0

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, access_token, log_path="", litemode=False, write_to_file=False,
                 reconnect=True, on_connect=None, on_message=None, on_error=None, on_close=None):
        self.access_token = access_token
        self.restart_flag = reconnect
        self._on_connect = on_connect
        self._on_message = on_message
        self._on_error = on_error
        self._on_close = on_close
        self._connected = False

    def connect(self):
        self._connected = True
        if self._on_connect:
            self._on_connect()

    def subscribe(self, symbols, data_type):
        if self._on_message:
            self._on_message({"symbol": symbols[0], "ltp": 123.45, "type": "sf"})

    def is_connected(self):
        return self._connected

    def close_connection(self):
        type(self).close_connection_calls += 1
        if self._connected:
            self.restart_flag = False
            self._connected = False
            if self._on_close:
                self._on_close({"reason": "closed"})


@pytest.fixture(autouse=True)
def _fake_fyers_sdk(monkeypatch):
    """Injects the fake as fyers_apiv3.FyersWebsocket.data_ws so _run_live's
    lazy `from fyers_apiv3.FyersWebsocket import data_ws` picks it up, and
    resets all process-wide state (the real risk this module's singleton
    guard exists for) between tests."""
    _FakeSDKSocket._instance = None
    _FakeSDKSocket.close_connection_calls = 0

    fake_module = types.ModuleType("fyers_apiv3.FyersWebsocket.data_ws")
    fake_module.FyersDataSocket = _FakeSDKSocket
    monkeypatch.setitem(sys.modules, "fyers_apiv3.FyersWebsocket.data_ws", fake_module)
    monkeypatch.setitem(sys.modules, "fyers_apiv3.FyersWebsocket", types.ModuleType("fyers_apiv3.FyersWebsocket"))
    monkeypatch.setitem(sys.modules, "fyers_apiv3", types.ModuleType("fyers_apiv3"))

    ws_module._active_live_owner = None
    yield
    ws_module._active_live_owner = None
    _FakeSDKSocket._instance = None


def _live_settings() -> Settings:
    return Settings(use_mock_fyers=False, fyers_client_id="test-client", fyers_access_token="test-token")


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_live_start_connects_and_delivers_a_tick():
    ticks = []
    socket = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=ticks.append, settings=_live_settings())

    socket.start()
    try:
        assert _wait_for(lambda: len(ticks) > 0)
        assert ticks[0]["symbol"] == "NSE:RELIANCE-EQ"
    finally:
        socket.stop()


def test_live_stop_actually_closes_the_sdk_connection():
    """The core bug fix: stop() must call the real close_connection(), not
    just stop our own wrapper thread."""
    socket = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=lambda t: None, settings=_live_settings())
    socket.start()
    assert _wait_for(lambda: socket._sdk_socket is not None and socket._sdk_socket.is_connected())

    socket.stop()

    assert _FakeSDKSocket.close_connection_calls == 1
    assert _FakeSDKSocket._instance.is_connected() is False
    assert socket.is_running is False


def test_stop_prevents_sdk_auto_reconnect():
    """close_connection() must set restart_flag=False -- the same flag the
    real SDK's on_close() checks before attempting to reconnect."""
    socket = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=lambda t: None, settings=_live_settings())
    socket.start()
    _wait_for(lambda: socket._sdk_socket is not None and socket._sdk_socket.is_connected())

    socket.stop()

    assert _FakeSDKSocket._instance.restart_flag is False


def test_repeated_stop_is_safe_and_idempotent():
    socket = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=lambda t: None, settings=_live_settings())
    socket.start()
    _wait_for(lambda: socket._sdk_socket is not None and socket._sdk_socket.is_connected())

    socket.stop()
    socket.stop()  # must not raise, must not double-fire on_close

    assert _FakeSDKSocket.close_connection_calls == 1  # second call was a safe no-op (already disconnected)
    assert socket.is_running is False


def test_start_stop_start_receives_data_again():
    ticks = []
    socket = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=ticks.append, settings=_live_settings())

    socket.start()
    assert _wait_for(lambda: len(ticks) >= 1)
    socket.stop()

    socket.start()
    try:
        assert _wait_for(lambda: len(ticks) >= 2)
    finally:
        socket.stop()


def test_concurrent_live_start_is_refused_not_hijacked():
    """Phase 2/3 finding: data_ws.FyersDataSocket is a process-wide
    singleton, so a second independent live wrapper must not be allowed to
    silently steal the first one's connection."""
    ticks_a, ticks_b = [], []
    socket_a = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=ticks_a.append, settings=_live_settings())
    socket_b = FyersMarketDataSocket(["NSE:TCS-EQ"], on_tick=ticks_b.append, settings=_live_settings())

    socket_a.start()
    try:
        assert _wait_for(lambda: len(ticks_a) >= 1)
        socket_b.start()  # should be refused, not hijack socket_a's connection
        assert socket_b.is_running is False
        assert socket_b._sdk_socket is None
    finally:
        socket_a.stop()


def test_ownership_is_released_after_stop_so_a_new_owner_can_start():
    socket_a = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=lambda t: None, settings=_live_settings())
    socket_a.start()
    _wait_for(lambda: socket_a._sdk_socket is not None and socket_a._sdk_socket.is_connected())
    socket_a.stop()

    ticks_b = []
    socket_b = FyersMarketDataSocket(["NSE:TCS-EQ"], on_tick=ticks_b.append, settings=_live_settings())
    socket_b.start()
    try:
        assert _wait_for(lambda: len(ticks_b) >= 1)
    finally:
        socket_b.stop()


def test_intentional_stop_logs_stopped_not_reconnecting(caplog):
    import logging

    socket = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=lambda t: None, settings=_live_settings())
    with caplog.at_level(logging.INFO, logger="app.integrations.fyers.websocket"):
        socket.start()
        _wait_for(lambda: socket._sdk_socket is not None and socket._sdk_socket.is_connected())
        socket.stop()

    messages = [r.message for r in caplog.records]
    assert any("[STOPPED]" in m for m in messages)
    assert not any("[RECONNECTING]" in m for m in messages)
    assert not any(
        "test-token" in m or "test-client:test-token" in m for m in messages
    )  # never log the access token
