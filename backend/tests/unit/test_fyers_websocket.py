import queue
import time

import pytest

from app.integrations.fyers.websocket import FyersMarketDataSocket


def test_rejects_empty_symbol_list():
    with pytest.raises(ValueError):
        FyersMarketDataSocket([], on_tick=lambda t: None)


def test_mock_mode_delivers_ticks_for_all_symbols():
    received: queue.Queue = queue.Queue()
    socket = FyersMarketDataSocket(["NSE:RELIANCE-EQ", "NSE:TCS-EQ"], on_tick=received.put)

    socket.start()
    try:
        assert socket.is_running
        seen_symbols = set()
        deadline = time.monotonic() + 5
        while len(seen_symbols) < 2 and time.monotonic() < deadline:
            tick = received.get(timeout=5)
            assert "symbol" in tick
            assert "ltp" in tick
            assert tick["ltp"] > 0
            seen_symbols.add(tick["symbol"])
        assert seen_symbols == {"NSE:RELIANCE-EQ", "NSE:TCS-EQ"}
    finally:
        socket.stop()

    assert not socket.is_running


def test_stop_is_idempotent_and_joins_thread():
    socket = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=lambda t: None)
    socket.start()
    socket.stop()
    socket.stop()  # must not raise
    assert not socket.is_running


def test_on_tick_exception_does_not_kill_the_feed_thread():
    calls = []

    def flaky_on_tick(tick):
        calls.append(tick)
        if len(calls) == 1:
            raise RuntimeError("boom")

    socket = FyersMarketDataSocket(["NSE:RELIANCE-EQ"], on_tick=flaky_on_tick)
    socket.start()
    try:
        deadline = time.monotonic() + 5
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.2)
        assert len(calls) >= 3  # thread kept running past the first exception
    finally:
        socket.stop()
