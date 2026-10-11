"""Public-facing live market-data service (Phase 4-7 real-time
architecture): combines the shared WebSocket hub's Redis-cached quotes
with REST-fetched, short-TTL-cached market depth, and classifies freshness
(LIVE/STALE/UNAVAILABLE) against one configurable threshold.

Depth is deliberately REST-fetched, not read from the WebSocket tick
stream: the only confirmed live-tick fields (symbol/ltp/type -- see
websocket.py's module docstring) carry no depth data. Treating a
quote-only feed as a source of depth would mean fabricating fields FYERS
never actually sent over that channel.
"""

import datetime as dt

from app.config import get_settings
from app.data.internal_models import DepthLevel, MarketDepth
from app.data.normalization import normalize_depth
from app.db.redis_client import get_redis
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.market_data import get_market_depth
from app.integrations.fyers.request_control import record_cache_hit
from app.services.cache_service import TTL_LIVE_DEPTH_SECONDS, get_json, live_depth_key, live_quote_key, set_json

FRESHNESS_LIVE = "LIVE"
FRESHNESS_STALE = "STALE"
FRESHNESS_UNAVAILABLE = "UNAVAILABLE"


def is_market_hours_ist(now_utc: dt.datetime | None = None) -> bool:
    """NSE's published equity trading window: Mon-Fri, 09:15-15:30 IST.
    India has no daylight-saving time, so a fixed +5:30 offset is correct
    (public NSE trading-hours information, not a guess)."""
    now_utc = now_utc or dt.datetime.now(dt.UTC)
    ist = now_utc + dt.timedelta(hours=5, minutes=30)
    if ist.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    minutes_since_midnight = ist.hour * 60 + ist.minute
    return 9 * 60 + 15 <= minutes_since_midnight <= 15 * 60 + 30


def classify_freshness(
    as_of: dt.datetime | None, stale_after_seconds: int | None = None, now_utc: dt.datetime | None = None
) -> str:
    """Never presents old data as live (Phase 7 requirement). `as_of=None`
    means no usable data exists at all -- UNAVAILABLE, not STALE.

    `now_utc` defaults to the real current time (every existing caller
    passes nothing, so behavior is unchanged) -- added only so
    classify_market_status() below can inject a single consistent instant
    into both this function and is_market_hours_ist(), rather than each
    silently reading its own real-time `now()` microseconds apart. Found
    while testing: passing an artificial `now_utc` to
    classify_market_status() alone, with this function still reading the
    real wall clock underneath it, produced inconsistent, confusing results
    -- deterministic tests need one injectable "now" that actually
    propagates everywhere it's used, not just at the outermost caller.

    Deliberately does NOT know about market hours -- this stayed the
    original 3-value LIVE/STALE/UNAVAILABLE contract on purpose (backward
    compatibility for existing callers: /api/market/live/{symbol},
    LiveMarketData.tsx). See classify_market_status() below for the
    market-hours-aware classification the confirmation engine actually
    needs; that's an additive extension, not a change to this function.
    """
    if as_of is None:
        return FRESHNESS_UNAVAILABLE
    threshold = (
        stale_after_seconds if stale_after_seconds is not None else get_settings().live_data_stale_after_seconds
    )
    now_utc = now_utc or dt.datetime.now(dt.UTC)
    age_seconds = (now_utc - as_of).total_seconds()
    return FRESHNESS_LIVE if age_seconds <= threshold else FRESHNESS_STALE


MARKET_STATUS_OPEN_LIVE = "MARKET_OPEN_LIVE"
MARKET_STATUS_CLOSED_LAST_AVAILABLE = "MARKET_CLOSED_LAST_AVAILABLE"


def classify_market_status(
    as_of: dt.datetime | None, stale_after_seconds: int | None = None, now_utc: dt.datetime | None = None
) -> str:
    """Market-hours-aware classification (Phase 6 hardening, 2026-09-20):
    confirmed live that a freshly-cached tick can be classified LIVE by
    classify_freshness() purely because our own cache write is recent, even
    when NSE is closed and that tick is really just the feed's last-known-
    price snapshot delivered on subscribe -- not genuine intraday activity.
    A Sunday validation run showed exactly this: freshness=LIVE with a
    same-second cache write, for data that was demonstrably a closed-market
    snapshot (all-zero ask ladder, matching the exchange's actual closed
    state, not a parsing bug -- see the depth semantics investigation).

    Returns one of: MARKET_OPEN_LIVE, MARKET_CLOSED_LAST_AVAILABLE, STALE,
    UNAVAILABLE -- a strict, additive extension of classify_freshness()'s
    3-value contract (new field on the confirmation response only;
    classify_freshness() itself and every existing caller of it are
    unchanged)."""
    now_utc = now_utc or dt.datetime.now(dt.UTC)
    base = classify_freshness(as_of, stale_after_seconds, now_utc=now_utc)
    if base in (FRESHNESS_UNAVAILABLE, FRESHNESS_STALE):
        return base
    return MARKET_STATUS_OPEN_LIVE if is_market_hours_ist(now_utc) else MARKET_STATUS_CLOSED_LAST_AVAILABLE


async def get_cached_live_quote(symbol: str) -> dict | None:
    """Reads the latest tick the shared WebSocket hub cached for `symbol`
    (mtf:live_quote:{symbol}). None if no tick has arrived within the
    cache's own TTL -- the caller (the API route) is responsible for
    turning that into an UNAVAILABLE/STALE classification, not this
    function fabricating a value."""
    redis = get_redis()
    return await get_json(redis, live_quote_key(symbol))


def _depth_to_cacheable_dict(depth: MarketDepth) -> dict:
    return {
        "symbol": depth.symbol,
        "total_buy_qty": depth.total_buy_qty,
        "total_sell_qty": depth.total_sell_qty,
        "top_bid": depth.top_bid,
        "top_ask": depth.top_ask,
        "spread": depth.spread,
        "bid_levels": [
            {"price": lvl.price, "quantity": lvl.quantity, "order_count": lvl.order_count} for lvl in depth.bid_levels
        ],
        "ask_levels": [
            {"price": lvl.price, "quantity": lvl.quantity, "order_count": lvl.order_count} for lvl in depth.ask_levels
        ],
        "as_of": depth.as_of.isoformat(),
    }


def _depth_from_cached_dict(data: dict) -> MarketDepth:
    return MarketDepth(
        symbol=data["symbol"],
        total_buy_qty=data["total_buy_qty"],
        total_sell_qty=data["total_sell_qty"],
        top_bid=data.get("top_bid"),
        top_ask=data.get("top_ask"),
        spread=data.get("spread"),
        bid_levels=[DepthLevel(**lvl) for lvl in data.get("bid_levels", [])],
        ask_levels=[DepthLevel(**lvl) for lvl in data.get("ask_levels", [])],
        as_of=dt.datetime.fromisoformat(data["as_of"]),
    )


async def get_live_depth(client: FyersClient, symbol: str) -> MarketDepth | None:
    """REST-fetched (via the existing /data/depth adapter), cached for
    TTL_LIVE_DEPTH_SECONDS (Phase 5) so repeated API calls within the same
    short window don't re-hit FYERS (Phase 13 request-discipline)."""
    # Mock mode: skip Redis entirely, matching every other caching function
    # in this codebase (_fetch_history, fno_service's options-chain/depth
    # caching) -- tests/mock runs expect fresh canned data per call.
    if client.use_mock:
        raw = await get_market_depth(client, symbol)
        return normalize_depth(symbol, raw)

    redis = get_redis()
    cache_key = live_depth_key(symbol)

    cached = await get_json(redis, cache_key)
    if cached is not None:
        await record_cache_hit("depth")
        return _depth_from_cached_dict(cached)

    raw = await get_market_depth(client, symbol)
    depth = normalize_depth(symbol, raw)
    if depth is None:
        return None

    await set_json(redis, cache_key, _depth_to_cacheable_dict(depth), TTL_LIVE_DEPTH_SECONDS)
    return depth
