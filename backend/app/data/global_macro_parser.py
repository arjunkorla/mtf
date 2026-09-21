"""Parses Yahoo Finance's chart API response into a clean internal shape
(see app/integrations/global_macro/yahoo_finance_client.py for the fetch
side and its important "unofficial API" caveat).

Research-layer evidence only (Phase 11 global/macro context) -- never
imported by scoring_engine.py, scanner_service.py, or any production
CandidateResponse field. `source` is carried on every quote specifically so
any future consumer must display where the number came from, not present it
as an authoritative feed.
"""

import datetime as dt
from dataclasses import dataclass

from app.logging_config import get_logger

logger = get_logger(__name__)

SOURCE_LABEL = "Yahoo Finance (unofficial API -- best-effort, not a licensed feed)"


@dataclass(frozen=True, slots=True)
class MacroQuote:
    label: str  # e.g. "S&P 500" -- the human-facing name from MACRO_SYMBOLS
    symbol: str  # the provider's own symbol, e.g. "^GSPC"
    price: float
    prev_close: float | None
    change_pct: float | None
    as_of: dt.datetime
    source: str = SOURCE_LABEL


def normalize_macro_quote(raw: dict, label: str) -> MacroQuote | None:
    """Returns None (never a fabricated value) if Yahoo's response is
    missing, malformed, or lacks a usable price -- a caller losing one
    macro symbol must not lose the rest (see global_macro_service.py)."""
    try:
        results = raw.get("chart", {}).get("result")
        if not results:
            return None
        meta = results[0].get("meta", {})

        price = meta.get("regularMarketPrice")
        if price is None:
            return None

        symbol = meta.get("symbol", "UNKNOWN")
        prev_close = meta.get("chartPreviousClose")
        change_pct = meta.get("regularMarketChangePercent")
        ts = meta.get("regularMarketTime")
        as_of = dt.datetime.fromtimestamp(int(ts), tz=dt.UTC) if ts else dt.datetime.now(dt.UTC)

        return MacroQuote(
            label=label,
            symbol=symbol,
            price=float(price),
            prev_close=float(prev_close) if prev_close is not None else None,
            change_pct=float(change_pct) if change_pct is not None else None,
            as_of=as_of,
        )
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        logger.debug("Skipping malformed macro quote for %s: %s", label, exc)
        return None
