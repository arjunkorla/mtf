"""Provider-agnostic internal models.

Everything downstream of app/integrations/fyers/* (validation, normalization,
engines) works exclusively with these types. No FYERS-specific field names or
response shapes may leak past app/data/normalization.py.
"""

import datetime as dt
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Candle:
    trade_date: dt.date
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: int
    change_pct: float
    as_of: dt.datetime


@dataclass(frozen=True, slots=True)
class DepthLevel:
    """One price level of a market-depth bid/ask ladder. Any field FYERS
    doesn't supply for a given level is None, never fabricated (Phase 6
    market-depth investigation)."""

    price: float | None
    quantity: int | None
    order_count: int | None


@dataclass(frozen=True, slots=True)
class MarketDepth:
    symbol: str
    total_buy_qty: int
    total_sell_qty: int
    top_bid: float | None
    top_ask: float | None
    spread: float | None
    bid_levels: list[DepthLevel]
    ask_levels: list[DepthLevel]
    as_of: dt.datetime


@dataclass(frozen=True, slots=True)
class FuturesContract:
    symbol: str
    ltp: float
    open_interest: float
    oi_change_pct: float | None
    volume: float
    price_change_pct: float | None = None
