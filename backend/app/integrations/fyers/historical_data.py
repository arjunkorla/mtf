"""FYERS `history` endpoint adapter -- daily/intraday OHLCV candles."""

import datetime as dt

from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.mock_responses import mock_history_response
from app.logging_config import get_logger

logger = get_logger(__name__)


async def get_daily_history(
    client: FyersClient,
    symbol: str,
    range_from: dt.date,
    range_to: dt.date,
) -> dict:
    """Returns the raw FYERS history response: {"s": "ok", "candles": [[ts, o, h, l, c, v], ...]}."""
    if client.use_mock:
        days = max(1, (range_to - range_from).days)
        end_date = dt.datetime(range_to.year, range_to.month, range_to.day, tzinfo=dt.UTC)
        return mock_history_response(bars=days, end_date=end_date)

    params = {
        "symbol": symbol,
        "resolution": "D",
        "date_format": "1",
        "range_from": range_from.isoformat(),
        "range_to": range_to.isoformat(),
        "cont_flag": "1",
    }
    return await client.get_data("/history", params=params)


async def get_intraday_history(
    client: FyersClient,
    symbol: str,
    resolution: str,
    range_from: dt.date,
    range_to: dt.date,
) -> dict:
    """Raw FYERS intraday candles ({"s": "ok", "candles": [[ts, o, h, l, c, v], ...]},
    ts = candle START in epoch seconds). FYERS caps minute resolutions at
    100 days per request; callers chunk longer ranges.

    Mock mode returns NO candles on purpose: this feeds the suggestion
    tracker, and synthetic candles would write fabricated outcomes."""
    if client.use_mock:
        return {"s": "ok", "candles": []}

    params = {
        "symbol": symbol,
        "resolution": resolution,
        "date_format": "1",
        "range_from": range_from.isoformat(),
        "range_to": range_to.isoformat(),
        "cont_flag": "1",
    }
    return await client.get_data("/history", params=params)
