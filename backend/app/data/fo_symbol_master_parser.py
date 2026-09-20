"""Resolves each underlying stock's near-month (soonest unexpired) single-
stock futures contract symbol from the FYERS NSE_FO symbol-master CSV
(Phase 1 F&O investigation).

FYERS does not officially publish this file's column layout (same caveat as
symbol_master_parser.py for NSE_CM -- and confirmed live 2026-09-20 to share
that file's column positions). Two columns matter here that NSE_CM leaves
blank/unused for equities:
  - column 8: expiry, a Unix timestamp (blank for non-expiring instruments)
  - column 13: the bare underlying ticker, e.g. "RELIANCE" for both
    NSE:RELIANCE26SEPFUT and NSE:RELIANCE26OCTFUT

Only single-stock futures (symbol matching NSE:<TICKER><YY><MON>FUT, no
CE/PE suffix) are considered -- index futures and options are out of scope
for this integration and are filtered out by the symbol pattern itself.
"""

import datetime as dt
import re
from dataclasses import dataclass

_FUT_SYMBOL_RE = re.compile(r"^NSE:[A-Z0-9&]+\d{2}[A-Z]{3}FUT$")

_EXPECTED_MIN_COLUMNS = 20
_COL_EXPIRY = 8
_COL_SYMBOL = 9
_COL_UNDERLYING_TICKER = 13


@dataclass(frozen=True, slots=True)
class ParsedFuture:
    symbol: str  # e.g. "NSE:RELIANCE26SEPFUT"
    underlying_ticker: str  # e.g. "RELIANCE" (bare, no exchange/series suffix)
    expiry: dt.date


def parse_fo_symbol_master_csv(raw_csv: str) -> list[ParsedFuture]:
    futures: list[ParsedFuture] = []

    for line in raw_csv.splitlines():
        line = line.strip()
        if not line:
            continue

        cols = line.split(",")
        if len(cols) < _EXPECTED_MIN_COLUMNS:
            continue

        symbol_raw = cols[_COL_SYMBOL].strip()
        if not _FUT_SYMBOL_RE.match(symbol_raw):
            continue  # options / index futures / malformed -- not a single-stock future

        expiry_raw = cols[_COL_EXPIRY].strip()
        try:
            expiry = dt.datetime.fromtimestamp(int(expiry_raw), tz=dt.UTC).date()
        except (ValueError, OSError):
            continue  # no/invalid expiry -- can't rank as near/next month, skip defensively

        underlying = cols[_COL_UNDERLYING_TICKER].strip()
        if not underlying:
            continue

        futures.append(ParsedFuture(symbol=symbol_raw, underlying_ticker=underlying, expiry=expiry))

    return futures


def find_near_month_contract(
    futures: list[ParsedFuture], underlying_ticker: str, as_of: dt.date | None = None
) -> ParsedFuture | None:
    """The soonest-expiring, not-yet-expired contract for `underlying_ticker`
    -- the standard "current month" convention."""
    as_of = as_of or dt.date.today()
    candidates = [f for f in futures if f.underlying_ticker == underlying_ticker and f.expiry >= as_of]
    if not candidates:
        return None
    return min(candidates, key=lambda f: f.expiry)
