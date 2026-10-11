"""Canned FYERS API v3 response payloads, shaped exactly like the documented
REST responses, so the adapter and everything downstream of it is testable
without real credentials (section 27). Used when settings.use_mock_fyers is
true, and directly by the test suite.
"""

import datetime as dt

MOCK_SYMBOL = "NSE:RELIANCE-EQ"


def mock_quotes_response(symbol: str = MOCK_SYMBOL) -> dict:
    return {
        "s": "ok",
        "d": [
            {
                "n": symbol,
                "s": "ok",
                "v": {
                    "cmd": 0,
                    "ask": 2951.5,
                    "bid": 2951.0,
                    "high_price": 2965.0,
                    "low_price": 2930.0,
                    "open_price": 2935.0,
                    "prev_close_price": 2932.4,
                    "lp": 2951.2,
                    "spread": 0.5,
                    "volume": 5_432_100,
                    "short_name": "RELIANCE",
                    "exchange": "NSE",
                    "description": "RELIANCE INDUSTRIES LTD",
                    "ch": 18.8,
                    "chp": 0.64,
                    "tt": int(dt.datetime.now(dt.UTC).timestamp()),
                },
            }
        ],
    }


def mock_history_response(bars: int = 260, base_price: float = 2500.0, end_date: dt.datetime | None = None) -> dict:
    """Generates a deterministic, mildly-trending OHLCV series for tests.

    `end_date` defaults to "now" (matching every live scanner/analysis call,
    which always asks for history up to today) -- but a historical backtest
    or walk-forward validation run asks for an older `range_to`, and without
    honoring that here, the mock series would always end at today regardless
    of what was requested, silently returning candles dated outside the
    requested window (discovered via a walk-forward run against mock data
    where older windows got zero signals because their dates simply didn't
    exist in the generated series).
    """
    import math

    anchor = end_date if end_date is not None else dt.datetime.now(dt.UTC)
    candles = []
    ts = int((anchor - dt.timedelta(days=bars - 1)).timestamp())
    price = base_price
    for i in range(bars):
        drift = 0.0009
        wobble = math.sin(i / 9) * 0.01
        price = max(1.0, price * (1 + drift + wobble))
        o = price * (1 - 0.003)
        h = price * (1 + 0.01)
        low = price * (1 - 0.01)
        c = price
        vol = int(400_000 + abs(math.sin(i / 6)) * 900_000)
        candles.append([ts, round(o, 2), round(h, 2), round(low, 2), round(c, 2), vol])
        ts += 86400
    return {"s": "ok", "candles": candles}


def mock_depth_response(symbol: str = MOCK_SYMBOL) -> dict:
    """Shaped exactly like a REAL /data/depth response for an NSE equity
    (confirmed live 2026-09-20): 5 bid levels + 5 ask levels, each with
    price/volume/ord (order count)."""
    return {
        "s": "ok",
        "d": {
            symbol: {
                "totalbuyqty": 125_000,
                "totalsellqty": 98_000,
                "bids": [
                    {"price": 2951.0, "volume": 500, "ord": 3},
                    {"price": 2950.9, "volume": 1200, "ord": 5},
                    {"price": 2950.8, "volume": 800, "ord": 2},
                    {"price": 2950.7, "volume": 400, "ord": 1},
                    {"price": 2950.6, "volume": 650, "ord": 4},
                ],
                "ask": [
                    {"price": 2951.5, "volume": 620, "ord": 5},
                    {"price": 2951.6, "volume": 900, "ord": 3},
                    {"price": 2951.7, "volume": 300, "ord": 2},
                    {"price": 2951.8, "volume": 700, "ord": 4},
                    {"price": 2951.9, "volume": 550, "ord": 1},
                ],
                "o": 2935.0,
                "h": 2965.0,
                "l": 2930.0,
                "c": 2932.4,
                "chp": 0.64,
                "atp": 2948.1,
                "v": 5_432_100,
            }
        },
    }


def mock_depth_response_missing_levels(symbol: str = MOCK_SYMBOL) -> dict:
    """A depth response with no bid/ask ladder at all -- e.g. an illiquid
    symbol or a field FYERS simply didn't populate this tick. Used to prove
    normalize_depth degrades to empty levels / None fields rather than
    fabricating data (Phase 6 requirement)."""
    return {
        "s": "ok",
        "d": {
            symbol: {
                "totalbuyqty": 0,
                "totalsellqty": 0,
                "o": 2935.0, "h": 2965.0, "l": 2930.0, "c": 2932.4,
            }
        },
    }


def mock_options_chain_response(symbol: str = MOCK_SYMBOL) -> dict:
    """Shaped exactly like a REAL /data/options-chain response (confirmed
    live 2026-09-20): the underlying's own row (option_type=="", strike=-1)
    carries futures price fields (fp/fpch/fpchp), never a FUT-symbol row --
    see fno.py's module docstring. Top-level callOi/putOi are real aggregate
    options Open Interest, independent of the per-strike rows.

    `indiavixData` (confirmed live 2026-09-21) is a real, market-wide
    India VIX quote riding along on every options-chain response regardless
    of the underlying -- not specific to this symbol. CE/PE rows carry no
    IV or Greeks fields (also confirmed live 2026-09-21: a real row has only
    ask/bid/fyToken/ltp/ltpch/ltpchp/oi/oich/oichp/option_type/prev_oi/
    strike_price/symbol/volume), so this mock deliberately omits them too --
    see normalize_india_vix() in normalization.py.
    """
    return {
        "s": "ok",
        "code": 200,
        "message": "",
        "data": {
            "callOi": 4_500_000,
            "putOi": 5_100_000,
            "indiavixData": {
                "ask": 0, "bid": 0, "description": "INDIAVIX-INDEX", "ex_symbol": "INDIAVIX",
                "exchange": "NSE", "fyToken": "101000000026017", "ltp": 11.47, "ltpch": 0.08,
                "ltpchp": 0.7, "option_type": "", "strike_price": -1, "symbol": "NSE:INDIAVIX-INDEX",
            },
            "optionsChain": [
                {
                    "symbol": symbol, "ex_symbol": symbol.split(":")[-1].split("-")[0],
                    "option_type": "", "strike_price": -1,
                    "ltp": 2951.2, "ltpch": 18.8, "ltpchp": 0.64,
                    "fp": 2958.0, "fpch": 12.4, "fpchp": 0.42,
                    "bid": 2951.0, "ask": 2951.5,
                },
                {
                    "symbol": f"{symbol.split(':')[-1].split('-')[0]}CE", "option_type": "CE", "strike_price": 2960,
                    "ltp": 15.0, "ltpch": 1.0, "ltpchp": 7.1, "oi": 250_000, "oich": 4.2, "oichp": 4.2,
                    "prev_oi": 240_000, "volume": 120_000, "bid": 14.5, "ask": 15.5,
                },
                {
                    "symbol": f"{symbol.split(':')[-1].split('-')[0]}PE", "option_type": "PE", "strike_price": 2960,
                    "ltp": 22.0, "ltpch": -0.5, "ltpchp": -2.2, "oi": 310_000, "oich": -1.1, "oichp": -1.1,
                    "prev_oi": 313_000, "volume": 95_000, "bid": 21.5, "ask": 22.5,
                },
            ],
        },
    }


def mock_futures_depth_response(symbol: str = "NSE:RELIANCE26SEPFUT") -> dict:
    """Shaped exactly like a REAL /data/depth response for an actual futures
    contract symbol (confirmed live 2026-09-20) -- the only FYERS endpoint
    that returns futures Open Interest ('oi', 'pdoi', 'oipercent'); neither
    /data/quotes nor /data/history carry it for any symbol type."""
    return {
        "s": "ok",
        "message": "Success",
        "d": {
            symbol: {
                "totalbuyqty": 466_500, "totalsellqty": 849_500,
                "bids": [{"price": 1242.0, "volume": 2000, "ord": 4}],
                "ask": [{"price": 1242.9, "volume": 2000, "ord": 1}],
                "o": 1247.0, "h": 1250.6, "l": 1234.4, "c": 1247.4,
                "chp": -0.43, "ch": -5.4,
                "ltp": 1242.0, "v": 10_342_500, "atp": 1244.11,
                "expiry": "1790676600",
                "oi": 127_287_000, "oiflag": True, "pdoi": 124_306_000, "oipercent": 2.4,
            }
        },
    }


def mock_margin_response(symbol: str = MOCK_SYMBOL, required_margin_pct: float = 25.0, ltp: float = 2951.2) -> dict:
    """Best-effort shape for the order-margin calculator response with a
    single MTF-productType order -- NOT confirmed live (see margin.py's
    module docstring). `required_margin_pct` is expressed back as a margin
    amount for 1 share at `ltp` so margin.extract_required_margin_pct()'s
    real parsing path is exercised end-to-end by tests, not bypassed."""
    margin_total = round(ltp * required_margin_pct / 100, 2)
    return {
        "s": "ok",
        "code": 200,
        "message": "",
        "data": {
            "margin_total": margin_total,
            "margin_avail": 100_000.0,
        },
    }


def mock_token_response() -> dict:
    return {"s": "ok", "code": 200, "message": "", "access_token": "mock-access-token"}
