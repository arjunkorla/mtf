"""Integration tests for GET /api/market/live/{symbol} and
GET /api/market/depth/{symbol} (Phase 6 real-time architecture).

Uses a fresh Redis client bound to each test's own event loop rather than
the module-level get_redis() singleton, which is @lru_cache'd for the
whole process and breaks across pytest-asyncio's per-test event loops once
any earlier test in the session has bound it to a (now-closed) loop --
confirmed to actually happen here: without this fixture, these tests
poisoned the singleton for later, unrelated tests in the same run (e.g.
test_fno_service.py) that also call the real get_redis(). Same fix already
applied to test_fno_service.py's and test_market_data_service.py's
equivalent cache tests.
"""

import datetime as dt

import pytest
from redis.asyncio import Redis

import app.services.market_data_service as market_data_service
from app.config import get_settings
from app.services.cache_service import live_quote_key, set_json

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_redis(monkeypatch):
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    monkeypatch.setattr(market_data_service, "get_redis", lambda: redis)
    yield redis
    await redis.aclose()


async def test_live_quote_unavailable_when_nothing_cached(app_client, fresh_redis):
    symbol = "NSE:__NEVER_CACHED__-EQ"
    resp = await app_client.get(f"/api/market/live/{symbol}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UNAVAILABLE"
    assert body["is_stale"] is True
    assert body["quote"] is None


async def test_live_quote_reports_live_for_a_fresh_tick(app_client, fresh_redis):
    symbol = "NSE:__FRESH_TICK__-EQ"
    tick = {"symbol": symbol, "ltp": 123.45, "volume": 1000, "as_of": dt.datetime.now(dt.UTC).isoformat()}
    await set_json(fresh_redis, live_quote_key(symbol), tick, 30)

    resp = await app_client.get(f"/api/market/live/{symbol}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "LIVE"
    assert body["is_stale"] is False
    assert body["quote"]["ltp"] == 123.45


async def test_live_quote_reports_stale_for_an_old_tick(app_client, fresh_redis):
    symbol = "NSE:__OLD_TICK__-EQ"
    old_as_of = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)).isoformat()
    tick = {"symbol": symbol, "ltp": 99.0, "volume": 500, "as_of": old_as_of}
    await set_json(fresh_redis, live_quote_key(symbol), tick, 3600)  # long TTL so it survives the read

    resp = await app_client.get(f"/api/market/live/{symbol}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "STALE"
    assert body["is_stale"] is True


async def test_market_depth_returns_5_levels(app_client):
    # /market/depth goes through FyersClient(), which is mock-mode in tests
    # (USE_MOCK_FYERS=true) and bypasses Redis entirely -- no fresh_redis needed.
    resp = await app_client.get("/api/market/depth/NSE:RELIANCE-EQ")
    assert resp.status_code == 200
    body = resp.json()
    assert body["depth"] is not None
    assert len(body["depth"]["bid_levels"]) == 5
    assert len(body["depth"]["ask_levels"]) == 5
    assert body["quote"] is None


async def test_market_data_response_never_leaks_credentials(app_client):
    resp = await app_client.get("/api/market/depth/NSE:RELIANCE-EQ")
    body_text = resp.text.lower()
    for forbidden in ("access_token", "client_secret", "secret_key", "password"):
        assert forbidden not in body_text
