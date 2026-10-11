"""FYERS `quotes` endpoint adapter -- current LTP/OHLC/volume for symbols."""

from app.db.redis_client import get_redis
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.mock_responses import mock_quotes_response
from app.integrations.fyers.request_control import record_cache_hit
from app.logging_config import get_logger
from app.services.cache_service import TTL_QUOTE_SECONDS, get_json, quote_key, set_json

logger = get_logger(__name__)


async def get_quotes(client: FyersClient, symbols: list[str]) -> dict:
    """Returns the raw FYERS quotes response for up to 50 symbols per call.

    Section 23: quotes are cached for TTL_QUOTE_SECONDS so a burst of callers
    (e.g. scanner + analysis for the same symbol) doesn't repeatedly hit
    FYERS. Caching is only applied to single-symbol lookups, the only shape
    the rest of the codebase currently calls with; a mixed-symbol batch
    always fetches fresh.
    """
    if client.use_mock:
        return mock_quotes_response(symbols[0] if symbols else "NSE:RELIANCE-EQ")

    if len(symbols) == 1:
        redis = get_redis()
        key = quote_key(symbols[0])
        cached = await get_json(redis, key)
        if cached is not None:
            await record_cache_hit("quotes")
            return cached

        data = await client.get_data("/quotes", params={"symbols": symbols[0]})
        await set_json(redis, key, data, TTL_QUOTE_SECONDS)
        return data

    return await client.get_data("/quotes", params={"symbols": ",".join(symbols)})
