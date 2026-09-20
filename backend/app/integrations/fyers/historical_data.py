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
