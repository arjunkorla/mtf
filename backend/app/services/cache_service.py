"""Redis-backed caching (section 23): recent quotes, stock analysis,
scanner results, short-lived market data. Every call degrades gracefully
if Redis is unreachable -- caching is an optimization, never a hard
dependency for correctness.
"""

import hashlib
import json

from redis.asyncio import Redis

from app.logging_config import get_logger

logger = get_logger(__name__)

TTL_QUOTE_SECONDS = 15
TTL_ANALYSIS_SECONDS = 300
TTL_SCANNER_RESULTS_SECONDS = 300
TTL_SECTOR_HISTORY_SECONDS = 900
TTL_STOCK_HISTORY_SECONDS = 900  # same rationale as sector history: daily candles, not intraday ticks
TTL_NEWS_FEED_SECONDS = 1800
TTL_BHAVCOPY_SECONDS = 14400  # 4h -- NSE publishes this once per trading day
# Phase 3 caching investigation: options-chain and futures-depth are live
# market snapshots (price/OI move intraday), unlike the once-daily data
# above -- 60s is short enough that a positioning signal for a 1-4 week
# scanner is never meaningfully stale, while still collapsing the repeated
# identical per-stock requests a scan (or back-to-back scans) would
# otherwise make (measured live: flat at 1 request/stock/run with zero
# caching, cold or warm, before this).
TTL_FNO_SECONDS = 60
# Phase 5 live-cache investigation: separate from TTL_QUOTE_SECONDS/quote_key
# (the existing REST /quotes cache) on purpose -- that key is written by a
# one-off REST fetch, this one by the shared WebSocket hub's continuous tick
# stream. Sharing one key would let a REST-fetched value be mistaken for a
# live tick (or vice versa) by whichever process last wrote it.
TTL_LIVE_QUOTE_SECONDS = 15
TTL_LIVE_DEPTH_SECONDS = 15
# Global macro context (Phase 11 research layer) changes slowly relative to
# a 1-4 week MTF setup and comes from a best-effort, unofficial source (see
# app/integrations/global_macro/yahoo_finance_client.py) -- cached longer
# than the FYERS live data above specifically so a flaky/blocked upstream
# doesn't turn into a fetch on every request.
TTL_GLOBAL_MACRO_SECONDS = 300


def quote_key(symbol: str) -> str:
    return f"mtf:quote:{symbol}"


def live_quote_key(symbol: str) -> str:
    return f"mtf:live_quote:{symbol}"


def live_depth_key(symbol: str) -> str:
    return f"mtf:live_depth:{symbol}"


def confirmation_history_key(symbol: str) -> str:
    """Bounded rolling history of past confirmation observations for one
    symbol (Phase 3 persistence investigation) -- capped by count
    (confirmation_persistence_window) AND by a hard TTL, so it can never
    grow unbounded even if a symbol is polled forever."""
    return f"mtf:confirmation_history:{symbol}"


def analysis_key(symbol: str) -> str:
    return f"mtf:analysis:{symbol}"


def scanner_results_key(run_id: int) -> str:
    return f"mtf:scanner_results:{run_id}"


def sector_history_key(sector_name: str) -> str:
    return f"mtf:sector_history:{sector_name}"


def stock_history_key(symbol: str) -> str:
    return f"mtf:stock_history:{symbol}"


def bhavcopy_key() -> str:
    return "mtf:bhavcopy:latest"


def options_chain_key(symbol: str) -> str:
    return f"mtf:options_chain:{symbol}"


def futures_depth_key(symbol: str) -> str:
    return f"mtf:futures_depth:{symbol}"


def global_macro_key(ticker: str) -> str:
    return f"mtf:global_macro:{ticker}"


def news_feed_key(feed_url: str) -> str:
    # A stable hash (unlike Python's built-in hash(), which is randomized
    # per-process for strings) so the cache key survives a process restart.
    return f"mtf:news_feed:{hashlib.sha1(feed_url.encode()).hexdigest()[:16]}"


async def get_text(redis: Redis, key: str) -> str | None:
    try:
        return await redis.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis GET failed for %s: %s", key, exc)
        return None


async def set_text(redis: Redis, key: str, value: str, ttl_seconds: int) -> None:
    try:
        await redis.set(key, value, ex=ttl_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis SET failed for %s: %s", key, exc)


async def get_json(redis: Redis, key: str) -> dict | None:
    try:
        raw = await redis.get(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis GET failed for %s: %s", key, exc)
        return None
    return json.loads(raw) if raw else None


async def set_json(redis: Redis, key: str, value: dict, ttl_seconds: int) -> None:
    try:
        await redis.set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis SET failed for %s: %s", key, exc)
