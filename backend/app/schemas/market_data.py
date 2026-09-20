"""Response models for the public live market-data API (Phase 6 real-time
architecture). Never includes credentials/tokens -- only symbol, price,
depth, and freshness metadata.
"""

import datetime as dt

from pydantic import BaseModel, Field


class LiveQuoteData(BaseModel):
    ltp: float
    volume: int | None = None


class DepthLevelSchema(BaseModel):
    price: float | None = None
    quantity: int | None = None
    order_count: int | None = None


class MarketDepthData(BaseModel):
    top_bid: float | None = None
    top_ask: float | None = None
    spread: float | None = None
    total_buy_qty: int | None = None
    total_sell_qty: int | None = None
    bid_levels: list[DepthLevelSchema] = Field(default_factory=list)
    ask_levels: list[DepthLevelSchema] = Field(default_factory=list)


class LiveMarketDataResponse(BaseModel):
    symbol: str
    source: str = "FYERS"
    timestamp: dt.datetime | None = None
    status: str  # LIVE | STALE | UNAVAILABLE (see market_data_service.classify_freshness)
    is_stale: bool
    quote: LiveQuoteData | None = None
    depth: MarketDepthData | None = None
