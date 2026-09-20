"""FYERS `depth` endpoint adapter -- market depth / breadth-related data."""

from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.mock_responses import mock_depth_response
from app.logging_config import get_logger

logger = get_logger(__name__)


async def get_market_depth(client: FyersClient, symbol: str) -> dict:
    if client.use_mock:
        return mock_depth_response(symbol)

    return await client.get_data("/depth", params={"symbol": symbol, "ohlcv_flag": "1"})
