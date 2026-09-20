"""Integration tests for GET /api/scanner/{symbol}/realtime-confirmation.

Uses a fresh Redis client bound to each test's own event loop (same fix
applied to test_api_market.py/test_market_data_service.py/
test_fno_service.py for the same underlying get_redis() singleton issue),
monkeypatched into both market_data_service (live-quote cache) and
realtime_confirmation_service (persistence history) since this endpoint
touches both.
"""

import datetime as dt

import pytest
from redis.asyncio import Redis

import app.services.market_data_service as market_data_service
import app.services.realtime_confirmation_service as realtime_confirmation_service
from app.config import get_settings
from app.services.cache_service import confirmation_history_key, live_quote_key, set_json

pytestmark = pytest.mark.asyncio

_TEST_SYMBOLS = [
    "NSE:RELIANCE-EQ", "NSE:HDFCBANK-EQ", "NSE:INFY-EQ", "NSE:LT-EQ",
    "NSE:ICICIBANK-EQ", "NSE:SBIN-EQ", "NSE:AXISBANK-EQ",
]


@pytest.fixture
async def fresh_redis(monkeypatch):
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    monkeypatch.setattr(market_data_service, "get_redis", lambda: redis)
    monkeypatch.setattr(realtime_confirmation_service, "get_redis", lambda: redis)
    # confirmation_history_key has a 1h TTL -- clean up before AND after so
    # neither this run nor the next one sees leftover observation counts.
    for symbol in _TEST_SYMBOLS:
        await redis.delete(confirmation_history_key(symbol))
    yield redis
    for symbol in _TEST_SYMBOLS:
        await redis.delete(confirmation_history_key(symbol))
    await redis.aclose()


async def test_realtime_confirmation_unknown_symbol_404(app_client, fresh_redis):
    resp = await app_client.get("/api/scanner/NSE:NOTAREALSTOCK-EQ/realtime-confirmation")
    assert resp.status_code == 404


async def test_realtime_confirmation_returns_full_shape(app_client, fresh_redis):
    symbol = "NSE:RELIANCE-EQ"
    tick = {"symbol": symbol, "ltp": 2960.0, "volume": 1000, "as_of": dt.datetime.now(dt.UTC).isoformat()}
    await set_json(fresh_redis, live_quote_key(symbol), tick, 30)

    resp = await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")
    assert resp.status_code == 200
    body = resp.json()

    for field in (
        "symbol", "timestamp", "freshness", "market_status", "confirmation_status", "confirmation_score", "data_quality",
        "price_confirmation", "volume_confirmation", "vwap_confirmation", "depth_confirmation",
        "spread_condition", "futures_confirmation", "persistence", "evidence", "warnings",
    ):
        assert field in body, f"missing field: {field}"

    assert body["symbol"] == symbol
    assert body["freshness"] == "LIVE"
    assert body["market_status"] in ("MARKET_OPEN_LIVE", "MARKET_CLOSED_LAST_AVAILABLE")
    assert "ladder_totals_consistent" in body["depth_confirmation"]
    assert body["vwap_confirmation"]["status"] == "UNAVAILABLE"  # always true today, see module docstring
    assert body["depth_confirmation"]["status"] in (
        "STRONG_BID", "MODERATE_BID", "BALANCED", "MODERATE_ASK", "STRONG_ASK", "UNAVAILABLE",
    )


async def test_realtime_confirmation_no_forbidden_language(app_client, fresh_redis):
    symbol = "NSE:HDFCBANK-EQ"
    tick = {"symbol": symbol, "ltp": 1650.0, "volume": 500, "as_of": dt.datetime.now(dt.UTC).isoformat()}
    await set_json(fresh_redis, live_quote_key(symbol), tick, 30)

    resp = await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")
    assert resp.status_code == 200
    body_text = resp.text.lower()
    for forbidden in ("guaranteed", "sure shot", "will rise", "will fall", "confirmed institutional", "smart money definitely"):
        assert forbidden not in body_text


async def test_realtime_confirmation_stale_quote_reduces_data_quality(app_client, fresh_redis):
    symbol = "NSE:INFY-EQ"
    old_as_of = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)).isoformat()
    tick = {"symbol": symbol, "ltp": 1500.0, "volume": 200, "as_of": old_as_of}
    await set_json(fresh_redis, live_quote_key(symbol), tick, 3600)

    resp = await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["freshness"] == "STALE"
    assert body["data_quality"] in ("LOW", "INSUFFICIENT_DATA")
    assert any("stale" in w.lower() for w in body["warnings"])


async def test_realtime_confirmation_unavailable_quote_gives_insufficient_data(app_client, fresh_redis):
    symbol = "NSE:LT-EQ"  # deliberately never cached
    resp = await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["freshness"] == "UNAVAILABLE"
    assert body["data_quality"] == "INSUFFICIENT_DATA"
    assert body["confirmation_status"] == "INSUFFICIENT_DATA"
    assert body["price_confirmation"]["status"] == "UNAVAILABLE"


async def test_realtime_confirmation_first_call_has_insufficient_persistence(app_client, fresh_redis):
    symbol = "NSE:ICICIBANK-EQ"
    await fresh_redis.delete(confirmation_history_key(symbol))  # persistence has a 1h TTL -- don't leak across runs
    tick = {"symbol": symbol, "ltp": 1200.0, "volume": 300, "as_of": dt.datetime.now(dt.UTC).isoformat()}
    await set_json(fresh_redis, live_quote_key(symbol), tick, 30)

    resp = await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["persistence"]["status"] == "INSUFFICIENT_OBSERVATIONS"
    assert body["persistence"]["observation_count"] == 1


async def test_realtime_confirmation_persists_across_repeated_calls(app_client, fresh_redis):
    symbol = "NSE:SBIN-EQ"
    await fresh_redis.delete(confirmation_history_key(symbol))  # persistence has a 1h TTL -- don't leak across runs
    tick = {"symbol": symbol, "ltp": 800.0, "volume": 400, "as_of": dt.datetime.now(dt.UTC).isoformat()}
    await set_json(fresh_redis, live_quote_key(symbol), tick, 30)

    resp1 = await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")
    resp2 = await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")
    assert resp1.json()["persistence"]["observation_count"] == 1
    assert resp2.json()["persistence"]["observation_count"] == 2


async def test_realtime_confirmation_never_leaks_credentials(app_client, fresh_redis):
    symbol = "NSE:AXISBANK-EQ"
    resp = await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")
    body_text = resp.text.lower()
    for forbidden in ("access_token", "client_secret", "secret_key", "password"):
        assert forbidden not in body_text


async def test_realtime_confirmation_persistence_history_has_a_ttl(app_client, fresh_redis):
    """Phase 13: the persistence key must never be written without a TTL --
    unbounded history growth is explicitly forbidden by the design."""
    symbol = "NSE:RELIANCE-EQ"
    tick = {"symbol": symbol, "ltp": 2960.0, "volume": 1000, "as_of": dt.datetime.now(dt.UTC).isoformat()}
    await set_json(fresh_redis, live_quote_key(symbol), tick, 30)

    await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")

    ttl = await fresh_redis.ttl(confirmation_history_key(symbol))
    assert ttl > 0  # a TTL is actually set, not -1 (no expiry) or -2 (missing key)
    assert ttl <= get_settings().confirmation_persistence_ttl_seconds


async def test_realtime_confirmation_market_closed_warning_present_when_applicable(app_client, fresh_redis):
    """This assertion is conditional on real wall-clock time (matches the
    live-observed Sunday behavior) rather than asserting a fixed outcome,
    since this test suite has no way to mock "now" for is_market_hours_ist()
    without touching production code -- see the final report for why."""
    from app.services.market_data_service import is_market_hours_ist

    symbol = "NSE:HDFCBANK-EQ"
    tick = {"symbol": symbol, "ltp": 1650.0, "volume": 500, "as_of": dt.datetime.now(dt.UTC).isoformat()}
    await set_json(fresh_redis, live_quote_key(symbol), tick, 30)

    resp = await app_client.get(f"/api/scanner/{symbol}/realtime-confirmation")
    body = resp.json()

    if is_market_hours_ist():
        assert body["market_status"] == "MARKET_OPEN_LIVE"
        assert not any("nse is currently closed" in w.lower() for w in body["warnings"])
    else:
        assert body["market_status"] == "MARKET_CLOSED_LAST_AVAILABLE"
        assert any("nse is currently closed" in w.lower() for w in body["warnings"])
        assert body["data_quality"] != "HIGH"
