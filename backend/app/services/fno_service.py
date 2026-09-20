"""F&O orchestration: resolves and fetches real futures + options data for
one underlying stock (Phase 1 F&O investigation), with short-TTL Redis
caching on both live FYERS calls involved (Phase 3 caching investigation).

No single FYERS endpoint provides both futures price and Open Interest
(confirmed live -- see app/integrations/fyers/fno.py's module docstring), so
build_candidate's F&O step is really two independent calls per F&O stock:
  1. /data/options-chain, for the underlying's live futures price fields
     and aggregate call/put Open Interest (put/call ratio).
  2. /data/depth for the resolved near-month futures contract, the only
     endpoint with real futures Open Interest.

Both are cached in Redis with a short TTL (TTL_FNO_SECONDS) -- measured live
before this change: options-chain and depth requests were flat at exactly
1 request/stock/run whether the run was seconds apart or not (no caching
existed), unlike history/sector data which already cached correctly.

The symbol-master parse (which contract is "near month") is a separate,
much slower-changing concern -- cached process-locally, not in Redis, since
FYERS only republishes it once a day.
"""

from app.data.fo_symbol_master_parser import ParsedFuture, find_near_month_contract, parse_fo_symbol_master_csv
from app.data.internal_models import FuturesContract
from app.data.normalization import normalize_futures_depth, normalize_options_oi
from app.db.redis_client import get_redis
from app.integrations.fyers.fno import get_futures_depth, get_options_chain
from app.integrations.fyers.fo_symbol_master import fetch_fo_symbol_master_csv
from app.integrations.fyers.fyers_client import FyersClient
from app.logging_config import get_logger
from app.services.cache_service import TTL_FNO_SECONDS, futures_depth_key, get_json, options_chain_key, set_json

logger = get_logger(__name__)

_fo_master_cache: list[ParsedFuture] | None = None


async def _get_fo_master(client: FyersClient) -> list[ParsedFuture]:
    global _fo_master_cache
    if _fo_master_cache is None:
        csv_text = await fetch_fo_symbol_master_csv(client.settings)
        _fo_master_cache = parse_fo_symbol_master_csv(csv_text)
    return _fo_master_cache


async def _get_cached_options_chain(client: FyersClient, symbol: str) -> dict:
    # Mock mode: skip Redis entirely, matching stock_service._fetch_history's
    # convention -- tests/mock runs expect fresh canned data per call.
    if client.use_mock:
        return await get_options_chain(client, symbol)

    redis = get_redis()
    cache_key = options_chain_key(symbol)
    cached = await get_json(redis, cache_key)
    if cached is not None:
        return cached

    raw = await get_options_chain(client, symbol)
    await set_json(redis, cache_key, raw, TTL_FNO_SECONDS)
    return raw


async def _get_cached_futures_depth(client: FyersClient, futures_symbol: str) -> dict:
    if client.use_mock:
        return await get_futures_depth(client, futures_symbol)

    redis = get_redis()
    cache_key = futures_depth_key(futures_symbol)
    cached = await get_json(redis, cache_key)
    if cached is not None:
        return cached

    raw = await get_futures_depth(client, futures_symbol)
    await set_json(redis, cache_key, raw, TTL_FNO_SECONDS)
    return raw


async def get_futures_contract(client: FyersClient, underlying_ticker: str) -> FuturesContract | None:
    """Returns None (never a fabricated value) when the ticker has no active
    futures contract, or the depth fetch fails / omits the symbol."""
    fo_master = await _get_fo_master(client)
    contract = find_near_month_contract(fo_master, underlying_ticker)
    if contract is None:
        return None

    try:
        depth_raw = await _get_cached_futures_depth(client, contract.symbol)
    except Exception as exc:  # noqa: BLE001 -- a depth outage must not sink the whole candidate
        logger.warning("Futures depth fetch failed for %s: %s", contract.symbol, exc)
        return None

    return normalize_futures_depth(depth_raw, contract.symbol)


async def get_fno_data(
    client: FyersClient, universe_symbol: str, underlying_ticker: str,
) -> tuple[FuturesContract | None, float | None, float | None]:
    """Returns (futures_contract, call_oi_total, put_oi_total) for one
    stock -- each independently None (never fabricated) when its own data
    genuinely couldn't be obtained, so a options-chain outage doesn't also
    take out futures OI or vice versa."""
    call_oi_total: float | None = None
    put_oi_total: float | None = None
    try:
        options_raw = await _get_cached_options_chain(client, universe_symbol)
        call_oi_total, put_oi_total = normalize_options_oi(options_raw)
    except Exception as exc:  # noqa: BLE001 -- an options-chain outage must not sink the whole candidate
        logger.warning("Options-chain fetch failed for %s: %s", universe_symbol, exc)

    try:
        futures = await get_futures_contract(client, underlying_ticker)
    except Exception as exc:  # noqa: BLE001 -- e.g. the FO symbol master fetch itself failing
        logger.warning("Futures contract resolution failed for %s: %s", underlying_ticker, exc)
        futures = None

    return futures, call_oi_total, put_oi_total
