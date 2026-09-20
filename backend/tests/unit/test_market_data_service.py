"""Tests for app.services.market_data_service (Phase 4-7 real-time
architecture): freshness classification and REST-depth caching."""

import datetime as dt

import pytest

from app.config import Settings
from app.integrations.fyers.fyers_client import FyersClient
from app.services.market_data_service import (
    classify_freshness,
    classify_market_status,
    get_live_depth,
    is_market_hours_ist,
)

def test_classify_freshness_recent_timestamp_is_live():
    as_of = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5)
    assert classify_freshness(as_of, stale_after_seconds=30) == "LIVE"


def test_classify_freshness_old_timestamp_is_stale():
    as_of = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=60)
    assert classify_freshness(as_of, stale_after_seconds=30) == "STALE"


def test_classify_freshness_none_is_unavailable():
    assert classify_freshness(None) == "UNAVAILABLE"


def test_classify_freshness_uses_configured_default_threshold():
    # default is 30s (app/config.py); 20s old must be LIVE, 40s old STALE
    as_of_fresh = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=20)
    as_of_old = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=40)
    assert classify_freshness(as_of_fresh) == "LIVE"
    assert classify_freshness(as_of_old) == "STALE"


def test_is_market_hours_ist_weekday_during_session():
    # Wednesday 2026-09-23, 10:00 IST = 04:30 UTC
    weekday_during = dt.datetime(2026, 9, 23, 4, 30, tzinfo=dt.UTC)
    assert is_market_hours_ist(weekday_during) is True


def test_is_market_hours_ist_weekday_before_open():
    weekday_before_open = dt.datetime(2026, 9, 23, 2, 0, tzinfo=dt.UTC)  # 07:30 IST
    assert is_market_hours_ist(weekday_before_open) is False


def test_is_market_hours_ist_weekend():
    # 2026-09-20 is a Sunday
    sunday = dt.datetime(2026, 9, 20, 6, 0, tzinfo=dt.UTC)
    assert is_market_hours_ist(sunday) is False


# --- classify_market_status (Phase 6 hardening) -------------------------------
# Regression coverage for the exact bug found live: a fresh cache write
# (classify_freshness -> LIVE) during closed-market hours must NOT be
# reported as genuinely live intraday activity.


def test_market_status_open_live_during_trading_hours():
    weekday_during = dt.datetime(2026, 9, 23, 4, 30, tzinfo=dt.UTC)  # Wed 10:00 IST
    as_of = weekday_during - dt.timedelta(seconds=5)
    assert classify_market_status(as_of, stale_after_seconds=30, now_utc=weekday_during) == "MARKET_OPEN_LIVE"


def test_market_status_closed_last_available_on_sunday_even_with_fresh_cache():
    """The exact scenario from the prior live validation: a same-second
    cache write on a Sunday must not be classified as genuinely live."""
    sunday = dt.datetime(2026, 9, 20, 17, 0, tzinfo=dt.UTC)
    as_of = sunday - dt.timedelta(seconds=1)
    assert classify_market_status(as_of, stale_after_seconds=30, now_utc=sunday) == "MARKET_CLOSED_LAST_AVAILABLE"


def test_market_status_closed_last_available_on_weekday_after_close():
    after_close = dt.datetime(2026, 9, 23, 10, 30, tzinfo=dt.UTC)  # Wed 16:00 IST, market shut at 15:30
    as_of = after_close - dt.timedelta(seconds=5)
    assert classify_market_status(as_of, stale_after_seconds=30, now_utc=after_close) == "MARKET_CLOSED_LAST_AVAILABLE"


def test_market_status_stale_regardless_of_market_hours():
    """An old cache entry is STALE (a real data-flow concern) whether or
    not the market happens to be open -- distinct from the "closed but
    fresh" case above."""
    weekday_during = dt.datetime(2026, 9, 23, 4, 30, tzinfo=dt.UTC)
    old_as_of = weekday_during - dt.timedelta(minutes=5)
    assert classify_market_status(old_as_of, stale_after_seconds=30, now_utc=weekday_during) == "STALE"


def test_market_status_unavailable_when_no_data():
    assert classify_market_status(None) == "UNAVAILABLE"


@pytest.mark.asyncio
async def test_get_live_depth_returns_5_levels_in_mock_mode():
    client = FyersClient()  # mock mode (USE_MOCK_FYERS=true, forced globally)
    try:
        depth = await get_live_depth(client, "NSE:RELIANCE-EQ")
        assert depth is not None
        assert len(depth.bid_levels) == 5
        assert len(depth.ask_levels) == 5
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_live_depth_caches_result_in_live_mode(monkeypatch):
    """Second call within the TTL must not hit FYERS again. Uses a fresh
    Redis client bound to this test's own event loop (not the module-level
    get_redis() singleton, which is @lru_cache'd for the process and breaks
    across pytest-asyncio's per-test event loops -- same issue documented
    in test_fno_service.py's equivalent cache test) and a monkeypatched
    fetcher so no real FYERS network call happens."""
    import app.services.market_data_service as market_data_service
    from app.config import get_settings
    from redis.asyncio import Redis
    from app.services.cache_service import live_depth_key
    from app.integrations.fyers.mock_responses import mock_depth_response

    symbol = "NSE:__TEST_DEPTH_CACHE__-EQ"
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    monkeypatch.setattr(market_data_service, "get_redis", lambda: redis)
    await redis.delete(live_depth_key(symbol))

    call_count = {"n": 0}

    async def _counting_get_market_depth(client, sym):
        call_count["n"] += 1
        return mock_depth_response(sym)

    monkeypatch.setattr(market_data_service, "get_market_depth", _counting_get_market_depth)

    live_client = FyersClient(settings=Settings(use_mock_fyers=False, fyers_client_id="t", fyers_access_token="t"))

    try:
        d1 = await get_live_depth(live_client, symbol)
        d2 = await get_live_depth(live_client, symbol)
        assert d1 is not None and d2 is not None
        assert call_count["n"] == 1
        assert len(d1.bid_levels) == 5
    finally:
        await redis.delete(live_depth_key(symbol))
        await redis.aclose()
