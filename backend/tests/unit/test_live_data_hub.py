"""Tests for LiveDataHub (Phase 2/3 real-time architecture): one shared
FyersMarketDataSocket, reference-counted per-symbol subscriptions across
multiple independent consumers. Runs in mock mode (USE_MOCK_FYERS=true,
forced globally in conftest.py) -- exercises the real subscribe/unsubscribe
logic, just against the mock tick generator instead of a live connection.
"""

import asyncio
import time

import pytest

from app.services.live_data_hub import LiveDataHub

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _drain_background_cache_writes():
    """_on_tick schedules a Redis-cache-write coroutine via
    run_coroutine_threadsafe from the socket's background thread; a tick
    fired right as a test's unsubscribe()/teardown races the per-test event
    loop closing can otherwise log a harmless but noisy 'Task was destroyed
    but it is pending' warning. A short grace period lets any final
    in-flight writes finish before the loop tears down."""
    yield
    await asyncio.sleep(0.2)


async def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


async def test_single_client_single_symbol():
    hub = LiveDataHub()
    sub_id, queue = hub.subscribe(["NSE:RELIANCE-EQ"])
    try:
        assert hub.subscriber_count("NSE:RELIANCE-EQ") == 1
        tick = await asyncio.wait_for(queue.get(), timeout=5)
        assert tick["symbol"] == "NSE:RELIANCE-EQ"
    finally:
        hub.unsubscribe(sub_id, ["NSE:RELIANCE-EQ"])


async def test_duplicate_subscription_does_not_double_subscribe_at_fyers():
    """Client A and Client B both want RELIANCE -- the underlying FYERS
    connection must only be told once."""
    hub = LiveDataHub()
    a_id, a_queue = hub.subscribe(["NSE:RELIANCE-EQ"])
    b_id, b_queue = hub.subscribe(["NSE:RELIANCE-EQ"])
    try:
        assert hub.subscriber_count("NSE:RELIANCE-EQ") == 2
        assert hub.active_symbols == ["NSE:RELIANCE-EQ"]  # one logical symbol, not two

        tick_a = await asyncio.wait_for(a_queue.get(), timeout=5)
        tick_b = await asyncio.wait_for(b_queue.get(), timeout=5)
        assert tick_a["symbol"] == tick_b["symbol"] == "NSE:RELIANCE-EQ"
    finally:
        hub.unsubscribe(a_id, ["NSE:RELIANCE-EQ"])
        hub.unsubscribe(b_id, ["NSE:RELIANCE-EQ"])


async def test_multi_symbol_client_and_partial_overlap():
    """Client A: RELIANCE. Client B: RELIANCE + HDFCBANK. Both must receive
    RELIANCE; only B receives HDFCBANK."""
    hub = LiveDataHub()
    a_id, a_queue = hub.subscribe(["NSE:RELIANCE-EQ"])
    b_id, b_queue = hub.subscribe(["NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ"])
    try:
        assert hub.subscriber_count("NSE:RELIANCE-EQ") == 2
        assert hub.subscriber_count("NSE:HDFCBANK-EQ") == 1
        assert set(hub.active_symbols) == {"NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ"}

        seen_a, seen_b = set(), set()
        deadline = time.monotonic() + 5
        while (not seen_a or "NSE:HDFCBANK-EQ" not in seen_b) and time.monotonic() < deadline:
            if not a_queue.empty():
                seen_a.add((await a_queue.get())["symbol"])
            if not b_queue.empty():
                seen_b.add((await b_queue.get())["symbol"])
            await asyncio.sleep(0.05)

        assert seen_a == {"NSE:RELIANCE-EQ"}  # A never receives HDFCBANK
        assert "NSE:HDFCBANK-EQ" in seen_b
    finally:
        hub.unsubscribe(a_id, ["NSE:RELIANCE-EQ"])
        hub.unsubscribe(b_id, ["NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ"])


async def test_client_disconnect_does_not_affect_other_clients_shared_symbol():
    hub = LiveDataHub()
    a_id, a_queue = hub.subscribe(["NSE:RELIANCE-EQ"])
    b_id, b_queue = hub.subscribe(["NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ"])
    try:
        assert hub.subscriber_count("NSE:RELIANCE-EQ") == 2

        hub.unsubscribe(a_id, ["NSE:RELIANCE-EQ"])  # Client A disconnects

        assert hub.subscriber_count("NSE:RELIANCE-EQ") == 1  # still alive for B
        assert hub.subscriber_count("NSE:HDFCBANK-EQ") == 1

        # B must keep receiving RELIANCE after A left
        while not b_queue.empty():
            b_queue.get_nowait()
        tick = await asyncio.wait_for(b_queue.get(), timeout=5)
        assert tick["symbol"] in ("NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ")
    finally:
        hub.unsubscribe(b_id, ["NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ"])


async def test_last_unsubscribe_tears_down_the_socket():
    hub = LiveDataHub()
    sub_id, _ = hub.subscribe(["NSE:RELIANCE-EQ"])
    assert hub._socket is not None

    hub.unsubscribe(sub_id, ["NSE:RELIANCE-EQ"])

    assert hub._socket is None
    assert hub.active_symbols == []


async def test_unsubscribe_is_idempotent():
    hub = LiveDataHub()
    sub_id, _ = hub.subscribe(["NSE:RELIANCE-EQ"])
    hub.unsubscribe(sub_id, ["NSE:RELIANCE-EQ"])
    hub.unsubscribe(sub_id, ["NSE:RELIANCE-EQ"])  # must not raise or double-decrement
    assert hub.active_symbols == []


async def test_subscribe_rejects_empty_symbol_list():
    hub = LiveDataHub()
    with pytest.raises(ValueError):
        hub.subscribe([])


async def test_new_subscriber_after_hub_emptied_gets_a_fresh_socket():
    hub = LiveDataHub()
    a_id, _ = hub.subscribe(["NSE:RELIANCE-EQ"])
    hub.unsubscribe(a_id, ["NSE:RELIANCE-EQ"])
    assert hub._socket is None

    b_id, b_queue = hub.subscribe(["NSE:HDFCBANK-EQ"])
    try:
        tick = await asyncio.wait_for(b_queue.get(), timeout=5)
        assert tick["symbol"] == "NSE:HDFCBANK-EQ"
    finally:
        hub.unsubscribe(b_id, ["NSE:HDFCBANK-EQ"])
