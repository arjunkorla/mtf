"""GET /api/market/live/{symbol}, GET /api/market/depth/{symbol} -- Phase 6
public live market-data API.

Two separate, cheap-by-default endpoints rather than one endpoint that
always fetches both: /live is a Redis-only read of whatever the shared
WebSocket hub (app/services/live_data_hub.py) has cached, so it costs
nothing extra to poll; /depth makes a (short-TTL-cached) REST call, kept
separate so a caller that only wants price never pays for a depth fetch it
didn't ask for (Phase 13 request-discipline). Both return the same envelope
shape, leaving the field they don't populate as null.

Never exposes access tokens, client secrets, or other credentials.
"""

from fastapi import APIRouter

from app.integrations.fyers.fyers_client import FyersClient
from app.schemas.market_data import DepthLevelSchema, LiveMarketDataResponse, LiveQuoteData, MarketDepthData
from app.services.market_data_service import classify_freshness, get_cached_live_quote, get_live_depth

router = APIRouter()


@router.get("/market/live/{symbol}", response_model=LiveMarketDataResponse)
async def get_live_quote_endpoint(symbol: str) -> LiveMarketDataResponse:
    cached = await get_cached_live_quote(symbol)

    as_of = None
    quote = None
    if cached is not None:
        as_of = _parse_as_of(cached.get("as_of"))
        quote = LiveQuoteData(ltp=cached["ltp"], volume=cached.get("volume"))

    status = classify_freshness(as_of)
    return LiveMarketDataResponse(
        symbol=symbol, timestamp=as_of, status=status, is_stale=(status != "LIVE"), quote=quote, depth=None,
    )


@router.get("/market/depth/{symbol}", response_model=LiveMarketDataResponse)
async def get_market_depth_endpoint(symbol: str) -> LiveMarketDataResponse:
    client = FyersClient()
    try:
        depth = await get_live_depth(client, symbol)
    finally:
        await client.aclose()

    if depth is None:
        return LiveMarketDataResponse(
            symbol=symbol, timestamp=None, status="UNAVAILABLE", is_stale=True, quote=None, depth=None,
        )

    status = classify_freshness(depth.as_of)
    depth_data = MarketDepthData(
        top_bid=depth.top_bid,
        top_ask=depth.top_ask,
        spread=depth.spread,
        total_buy_qty=depth.total_buy_qty,
        total_sell_qty=depth.total_sell_qty,
        bid_levels=[
            DepthLevelSchema(price=lvl.price, quantity=lvl.quantity, order_count=lvl.order_count)
            for lvl in depth.bid_levels
        ],
        ask_levels=[
            DepthLevelSchema(price=lvl.price, quantity=lvl.quantity, order_count=lvl.order_count)
            for lvl in depth.ask_levels
        ],
    )
    return LiveMarketDataResponse(
        symbol=symbol, timestamp=depth.as_of, status=status, is_stale=(status != "LIVE"), quote=None, depth=depth_data,
    )


def _parse_as_of(raw: str | None):
    import datetime as dt

    if raw is None:
        return None
    try:
        return dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
