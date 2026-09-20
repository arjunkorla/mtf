"""Delivery-percentage collection (section 9's "delivery data" proxy) --
the gap explicitly left open in the last two sessions because no confirmed
public source had been found. NSE's own daily bhavcopy CSV
(app/integrations/nse/bhavcopy_client.py) fills it: one EOD file covers the
whole market, so it's fetched and cached once (not per-stock).

A fetch/parse failure never breaks candidate scoring -- caught here and
logged; callers get None, which institutional_footprint_engine.py already
treats as "this proxy is unavailable," never a fabricated value.
"""

from app.data.bhavcopy_parser import DeliveryMetrics, parse_bhavcopy_csv
from app.db.redis_client import get_redis
from app.integrations.nse.bhavcopy_client import fetch_latest_bhavcopy_csv
from app.logging_config import get_logger
from app.services.cache_service import TTL_BHAVCOPY_SECONDS, bhavcopy_key, get_text, set_text

logger = get_logger(__name__)


async def _get_bhavcopy_csv() -> str | None:
    redis = get_redis()
    cache_key = bhavcopy_key()

    cached = await get_text(redis, cache_key)
    if cached is not None:
        return cached

    try:
        csv_text, trade_date = await fetch_latest_bhavcopy_csv()
    except Exception as exc:  # noqa: BLE001 -- an NSE outage must never break a candidate build
        logger.warning("Bhavcopy fetch failed, delivery data unavailable this run: %s", exc)
        return None

    await set_text(redis, cache_key, csv_text, TTL_BHAVCOPY_SECONDS)
    logger.info("Fetched NSE bhavcopy for %s", trade_date)
    return csv_text


async def get_delivery_metrics(ticker: str) -> DeliveryMetrics | None:
    """`ticker` is the bare NSE symbol, e.g. "RELIANCE" (matches
    Stock.symbol.split(':')[-1].split('-')[0], same convention used
    throughout app/services/stock_service.py).
    """
    csv_text = await _get_bhavcopy_csv()
    if csv_text is None:
        return None

    parsed = parse_bhavcopy_csv(csv_text)
    return parsed.by_symbol.get(ticker)
