"""Tests for app.services.fno_service (Phase 1 F&O investigation) --
resolves a real futures symbol via the FO symbol master, then fetches its
market depth for OI/price. Runs in USE_MOCK_FYERS=true mode (module-level
fixture in conftest.py), so these exercise the real code path against the
mock CSV/depth responses, not synthetic stand-ins for the service itself.
"""

import pytest

import app.services.fno_service as fno_service
from app.config import Settings
from app.integrations.fyers.fyers_client import FyersClient

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_fo_master_cache():
    """The module-level cache must not leak state between tests."""
    fno_service._fo_master_cache = None
    yield
    fno_service._fo_master_cache = None


def _mock_client() -> FyersClient:
    return FyersClient(settings=Settings(use_mock_fyers=True))


def _live_client() -> FyersClient:
    """use_mock_fyers=False so caching/fetch code takes the real (here,
    monkeypatched) path instead of the mock-mode bypass. use_mock is a
    read-only property (no setter), so this must be set at construction."""
    return FyersClient(settings=Settings(use_mock_fyers=False, fyers_client_id="test-client", fyers_access_token="test-token"))


async def test_get_futures_contract_returns_real_shaped_data_for_known_ticker():
    client = _mock_client()
    contract = await fno_service.get_futures_contract(client, "RELIANCE")
    assert contract is not None
    assert contract.symbol == "NSE:RELIANCE26SEPFUT"
    assert contract.open_interest > 0
    assert contract.oi_change_pct is not None


async def test_get_futures_contract_returns_none_for_unknown_ticker():
    client = _mock_client()
    contract = await fno_service.get_futures_contract(client, "NOTAREALTICKER")
    assert contract is None


async def test_fo_master_is_cached_across_calls(monkeypatch):
    client = _mock_client()
    call_count = {"n": 0}
    original_fetch = fno_service.fetch_fo_symbol_master_csv

    async def _counting_fetch(settings=None):
        call_count["n"] += 1
        return await original_fetch(settings)

    monkeypatch.setattr(fno_service, "fetch_fo_symbol_master_csv", _counting_fetch)

    await fno_service.get_futures_contract(client, "RELIANCE")
    await fno_service.get_futures_contract(client, "RELIANCE")

    assert call_count["n"] == 1


async def test_get_fno_data_returns_all_none_when_both_calls_fail(monkeypatch):
    """Safe error handling (Phase 3 requirement): an options-chain AND
    futures-depth outage must degrade to unavailable, never raise, never
    fabricate a value."""
    from app.integrations.fyers.fo_symbol_master import _MOCK_CSV

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated FYERS outage")

    async def _fake_fo_master_fetch(settings=None):
        return _MOCK_CSV  # avoid a real network fetch; not what this test is about

    monkeypatch.setattr(fno_service, "get_options_chain", _boom)
    monkeypatch.setattr(fno_service, "get_futures_depth", _boom)
    monkeypatch.setattr(fno_service, "fetch_fo_symbol_master_csv", _fake_fo_master_fetch)

    client = _live_client()  # forces the code path through the (monkeypatched) live fetchers
    futures, call_oi, put_oi = await fno_service.get_fno_data(client, "NSE:RELIANCE-EQ", "RELIANCE")

    assert futures is None
    assert call_oi is None
    assert put_oi is None


async def test_get_fno_data_options_chain_failure_does_not_block_futures_depth(monkeypatch):
    """The two data sources are independent -- one failing must not prevent
    the other from being returned."""

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated options-chain outage")

    monkeypatch.setattr(fno_service, "get_options_chain", _boom)

    client = _mock_client()
    futures, call_oi, put_oi = await fno_service.get_fno_data(client, "NSE:RELIANCE-EQ", "RELIANCE")

    assert futures is not None  # depth path (mock) still succeeded
    assert call_oi is None
    assert put_oi is None


async def test_options_chain_cache_avoids_duplicate_live_requests(monkeypatch):
    """Phase 3: a real (non-mock) request must hit the underlying fetcher
    only once per TTL window -- the second call is served from Redis.

    Uses a fresh Redis client bound to this test's own event loop rather
    than the module-level get_redis() singleton: that singleton is
    @lru_cache'd for the life of the process, so a connection first opened
    under an earlier test's (now-closed) event loop breaks here under
    pytest-asyncio's function-scoped loops -- a pre-existing limitation of
    that global-singleton pattern, not something this test should paper
    over by avoiding real Redis entirely."""
    from redis.asyncio import Redis

    from app.config import get_settings
    from app.services.cache_service import options_chain_key

    symbol = "NSE:__TEST_CACHE_SYMBOL__-EQ"
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    monkeypatch.setattr(fno_service, "get_redis", lambda: redis)
    await redis.delete(options_chain_key(symbol))

    call_count = {"n": 0}

    async def _counting_options_chain(client, sym):
        call_count["n"] += 1
        return {"s": "ok", "data": {"callOi": 1.0, "putOi": 2.0, "optionsChain": []}}

    monkeypatch.setattr(fno_service, "get_options_chain", _counting_options_chain)

    client = _live_client()  # exercise the Redis-backed path, not the mock-mode bypass

    try:
        await fno_service._get_cached_options_chain(client, symbol)
        await fno_service._get_cached_options_chain(client, symbol)
        assert call_count["n"] == 1
    finally:
        await redis.delete(options_chain_key(symbol))
        await redis.aclose()
