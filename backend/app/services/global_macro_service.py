"""Global macro/market context (Phase 11 research layer): fetches and
caches the configured MACRO_SYMBOLS from Yahoo Finance (see
app/integrations/global_macro/yahoo_finance_client.py for the important
"unofficial API" caveat -- every MacroQuote carries `source` so this is
never mistaken for a licensed feed).

Research-layer evidence only. Never imported by scoring_engine.py,
scanner_service.py, or any production CandidateResponse field -- mirrors
how app/data/normalization.py's normalize_india_vix() is kept separate from
the production score until separately approved for integration.

One symbol failing (fetch error, malformed response, Yahoo blocking this
endpoint entirely) must never take down the others -- each is fetched and
cached independently, and a missing symbol is simply absent from the
returned list, never a fabricated value.
"""

import asyncio

from app.config import Settings, get_settings
from app.data.global_macro_parser import MacroQuote, normalize_macro_quote
from app.db.redis_client import get_redis
from app.integrations.global_macro.yahoo_finance_client import MACRO_SYMBOLS, fetch_macro_chart
from app.logging_config import get_logger
from app.services.cache_service import TTL_GLOBAL_MACRO_SECONDS, get_json, global_macro_key, set_json

logger = get_logger(__name__)


async def _get_cached_macro_chart(ticker: str, settings: Settings) -> dict:
    # Mock mode: skip Redis entirely, matching every other caching function
    # in this codebase (_fetch_history, fno_service's options-chain caching)
    # -- tests/mock runs expect fresh canned data per call.
    if settings.use_mock_fyers:
        return await fetch_macro_chart(ticker, settings)

    redis = get_redis()
    cache_key = global_macro_key(ticker)
    cached = await get_json(redis, cache_key)
    if cached is not None:
        return cached

    raw = await fetch_macro_chart(ticker, settings)
    await set_json(redis, cache_key, raw, TTL_GLOBAL_MACRO_SECONDS)
    return raw


async def _get_one_macro_quote(label: str, ticker: str, settings: Settings) -> MacroQuote | None:
    try:
        raw = await _get_cached_macro_chart(ticker, settings)
        return normalize_macro_quote(raw, label)
    except Exception as exc:  # noqa: BLE001 -- one symbol's outage must not sink the rest
        logger.warning("Global macro fetch failed for %s (%s): %s", label, ticker, exc)
        return None


async def get_global_macro_snapshot(settings: Settings | None = None) -> list[MacroQuote]:
    """Returns whatever MACRO_SYMBOLS entries were genuinely fetchable right
    now -- never the full list padded with fabricated values. An empty list
    means the upstream is unavailable, which callers must render as
    GLOBAL_CONTEXT unavailable, not silently drop."""
    settings = settings or get_settings()

    results = await asyncio.gather(
        *(_get_one_macro_quote(label, ticker, settings) for label, ticker in MACRO_SYMBOLS.items())
    )
    return [quote for quote in results if quote is not None]
