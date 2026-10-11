"""Tests for app.services.candidate_live_subscription_service (Phase 6
Objective 1). Runs in USE_MOCK_FYERS=true mode, so the shared LiveDataHub's
FyersMarketDataSocket generates real synthetic ticks on its own background
thread (see websocket.py's _run_mock) -- these tests exercise the real
subscribe/settle/read/unsubscribe lifecycle, not a stand-in for it.
"""

import pytest

from app.services.candidate_live_subscription_service import collect_live_quotes_for_candidates
from app.services.live_data_hub import live_data_hub

pytestmark = pytest.mark.asyncio


async def test_empty_symbols_never_subscribes():
    result = await collect_live_quotes_for_candidates([])
    assert result == {}
    assert live_data_hub.active_symbols == []


async def test_collects_live_quotes_via_the_shared_hub_and_unsubscribes_after():
    symbols = ["NSE:RELIANCE-EQ", "NSE:TCS-EQ"]
    result = await collect_live_quotes_for_candidates(symbols, settle_seconds=0.3)

    assert set(result.keys()) == set(symbols)
    # Mock ticks fire immediately on thread start (see websocket.py's
    # _run_mock), so a 0.3s settle window should have captured at least one.
    assert any(v is not None for v in result.values())
    # No subscription leak: the hub is back to empty once we're done.
    assert live_data_hub.active_symbols == []


async def test_missing_websocket_quote_returns_none_not_fabricated():
    """Zero settle time means we read the cache before any tick can
    possibly have arrived -- an honest None, not a guessed value."""
    result = await collect_live_quotes_for_candidates(["NSE:SBIN-EQ"], settle_seconds=0.0)
    assert result["NSE:SBIN-EQ"] is None
    assert live_data_hub.active_symbols == []


async def test_unsubscribes_even_when_reading_the_cache_raises(monkeypatch):
    import app.services.candidate_live_subscription_service as module

    async def _boom(symbol):
        raise RuntimeError("simulated cache read failure")

    monkeypatch.setattr(module, "get_cached_live_quote", _boom)

    with pytest.raises(RuntimeError):
        await collect_live_quotes_for_candidates(["NSE:RELIANCE-EQ"], settle_seconds=0.0)

    # try/finally must have unsubscribed anyway -- no dangling subscription.
    assert live_data_hub.active_symbols == []


async def test_preserves_an_existing_subscribers_reference_count():
    """A real frontend client already subscribed to a symbol must keep its
    own subscription alive regardless of what this module does -- proven by
    checking the hub's reference count directly, not just active_symbols."""
    other_subscriber_id, _queue = live_data_hub.subscribe(["NSE:INFY-EQ"])
    try:
        assert live_data_hub.subscriber_count("NSE:INFY-EQ") == 1

        await collect_live_quotes_for_candidates(["NSE:INFY-EQ", "NSE:HDFCBANK-EQ"], settle_seconds=0.2)

        # Our subscription released, but the pre-existing one is untouched.
        assert live_data_hub.subscriber_count("NSE:INFY-EQ") == 1
        assert "NSE:HDFCBANK-EQ" not in live_data_hub.active_symbols
        assert "NSE:INFY-EQ" in live_data_hub.active_symbols
    finally:
        live_data_hub.unsubscribe(other_subscriber_id, ["NSE:INFY-EQ"])

    assert live_data_hub.active_symbols == []
