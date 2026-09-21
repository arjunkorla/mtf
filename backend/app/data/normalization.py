"""Normalizes raw FYERS API responses into provider-agnostic internal models
(section 6). This is the only module allowed to know the FYERS response shape.
"""

import datetime as dt

from app.data.internal_models import Candle, DepthLevel, FuturesContract, MarketDepth, Quote
from app.logging_config import get_logger

logger = get_logger(__name__)


def normalize_history(raw: dict) -> list[Candle]:
    candles_raw = raw.get("candles", [])
    candles: list[Candle] = []
    for row in candles_raw:
        ts, o, h, low, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
        trade_date = dt.datetime.fromtimestamp(ts, tz=dt.UTC).date()
        candles.append(Candle(trade_date=trade_date, open=o, high=h, low=low, close=c, volume=int(v)))
    candles.sort(key=lambda c: c.trade_date)
    return candles


def normalize_quote(raw: dict) -> Quote | None:
    entries = raw.get("d", [])
    if not entries:
        return None
    entry = entries[0]
    v = entry.get("v", {})
    symbol = entry.get("n", v.get("short_name", "UNKNOWN"))
    lp = v.get("lp")
    if lp is None:
        return None
    ts = v.get("tt")
    as_of = dt.datetime.fromtimestamp(int(ts), tz=dt.UTC) if ts else dt.datetime.now(dt.UTC)
    return Quote(
        symbol=symbol,
        ltp=float(lp),
        open=float(v.get("open_price", lp)),
        high=float(v.get("high_price", lp)),
        low=float(v.get("low_price", lp)),
        prev_close=float(v.get("prev_close_price", lp)),
        volume=int(v.get("volume", 0)),
        change_pct=float(v.get("chp", 0.0)),
        as_of=as_of,
    )


def _parse_depth_levels(raw_levels: list[dict] | None) -> list[DepthLevel]:
    """Phase 6 market-depth investigation: FYERS' real /data/depth response
    (confirmed live 2026-09-20) carries up to 5 levels each in 'bids'/'ask',
    each with 'price', 'volume' (quantity), and 'ord' (order count at that
    level). Any level entry missing one of these keeps it None rather than
    fabricating a value; levels beyond the 5th (not expected from FYERS,
    but not verified as impossible) are dropped by the caller, not here."""
    if not raw_levels:
        return []
    levels = []
    for entry in raw_levels:
        price = entry.get("price")
        qty = entry.get("volume")
        order_count = entry.get("ord")
        levels.append(
            DepthLevel(
                price=float(price) if price is not None else None,
                quantity=int(qty) if qty is not None else None,
                order_count=int(order_count) if order_count is not None else None,
            )
        )
    return levels


def normalize_depth(symbol: str, raw: dict) -> MarketDepth | None:
    d = raw.get("d", {}).get(symbol)
    if d is None:
        return None

    bid_levels = _parse_depth_levels(d.get("bids"))[:5]
    ask_levels = _parse_depth_levels(d.get("ask"))[:5]

    top_bid = bid_levels[0].price if bid_levels else None
    top_ask = ask_levels[0].price if ask_levels else None
    # Spread is a standard derived value from two real fields, not a
    # fabricated one -- but only computed when both sides are genuinely
    # present, per the "null over invented" rule.
    spread = (top_ask - top_bid) if (top_bid is not None and top_ask is not None) else None

    return MarketDepth(
        symbol=symbol,
        total_buy_qty=int(d.get("totalbuyqty", 0)),
        total_sell_qty=int(d.get("totalsellqty", 0)),
        top_bid=top_bid,
        top_ask=top_ask,
        spread=spread,
        bid_levels=bid_levels,
        ask_levels=ask_levels,
        as_of=dt.datetime.now(dt.UTC),
    )


def normalize_options_oi(raw: dict) -> tuple[float | None, float | None]:
    """Extracts aggregate call/put Open Interest from a FYERS options-chain
    response (Phase 1 F&O investigation) -- confirmed live 2026-09-20 that
    these are real top-level fields (`callOi`/`putOi`), independent of the
    per-strike CE/PE rows the existing options-chain fetch already parses."""
    data = raw.get("data", {})
    call_oi = data.get("callOi")
    put_oi = data.get("putOi")
    return (
        float(call_oi) if call_oi is not None else None,
        float(put_oi) if put_oi is not None else None,
    )


def normalize_india_vix(raw: dict) -> float | None:
    """Extracts the India VIX level from a FYERS options-chain response
    (confirmed live 2026-09-21): `data.indiavixData.ltp` is a real,
    market-wide quote that rides along on every options-chain call
    regardless of the underlying requested -- not specific to one stock.
    Zero extra API cost since options-chain is already fetched per F&O
    candidate; this is a pure additive extraction, not a new data source.

    Research-layer evidence only (section: institutional footprint proxy
    v2 / market regime) -- not wired into fno_engine.py, FnoData, or
    scoring_engine.py, which never reference this function.
    """
    vix = raw.get("data", {}).get("indiavixData", {}).get("ltp")
    return float(vix) if vix is not None else None


def normalize_futures_depth(raw: dict, symbol: str) -> FuturesContract | None:
    """Normalizes a FYERS market-depth response for an actual futures
    contract symbol (Phase 1 F&O investigation). Confirmed live 2026-09-20
    that /data/depth is the only FYERS endpoint that returns futures Open
    Interest ('oi', 'pdoi', 'oipercent') -- /data/quotes and /data/history
    do not carry OI for any symbol type (also confirmed against FYERS'
    own support documentation)."""
    entry = raw.get("d", {}).get(symbol)
    if entry is None:
        return None
    ltp = entry.get("ltp")
    if ltp is None:
        return None
    oi = entry.get("oi")
    oipercent = entry.get("oipercent")
    chp = entry.get("chp")
    return FuturesContract(
        symbol=symbol,
        ltp=float(ltp),
        open_interest=float(oi) if oi is not None else 0.0,
        oi_change_pct=float(oipercent) if oipercent is not None else None,
        volume=float(entry.get("v", 0.0)),
        price_change_pct=float(chp) if chp is not None else None,
    )


def normalize_futures_chain(raw: dict) -> list[FuturesContract]:
    entries = raw.get("data", {}).get("optionsChain", [])
    contracts: list[FuturesContract] = []
    for e in entries:
        symbol = e.get("symbol", "")
        if "FUT" not in symbol:
            continue
        contracts.append(
            FuturesContract(
                symbol=symbol,
                ltp=float(e.get("ltp", 0.0)),
                open_interest=float(e.get("oi", 0.0)),
                oi_change_pct=float(e["oich"]) if e.get("oich") is not None else None,
                volume=float(e.get("volume", 0.0)),
            )
        )
    return contracts
