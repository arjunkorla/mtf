"""Parses the FYERS NSE_CM symbol-master CSV into validated ParsedSymbol
records (section 5 -- expands the universe beyond the 20-stock dev seed).

FYERS does not officially publish the column layout of this file. The
mapping below was inferred from a live sample plus cross-referenced
community sources (see app/integrations/fyers/symbol_master.py), so every
row is validated defensively rather than trusted blindly:
  - wrong column count -> row skipped
  - symbol column doesn't look like "NSE:<TICKER>-<SERIES>" -> row skipped
  - ISIN column present but doesn't match the ISIN pattern -> row skipped

A column-order change upstream will show up as a spike in `skipped` rather
than silently corrupting the stocks table -- callers should treat a high
skip ratio as a signal to re-verify the mapping, not ignore it.

Only the equity ("EQ") series is imported: "BE"/"BZ"/"SM"/etc suffixes mark
trade-to-trade or restricted series that are not MTF-relevant here.
"""

import re
from dataclasses import dataclass

from app.logging_config import get_logger

logger = get_logger(__name__)

_SYMBOL_RE = re.compile(r"^NSE:([A-Z0-9&.\-]+)-([A-Z]{2,3})$")
_ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")

_EXPECTED_MIN_COLUMNS = 20

# 0-indexed column positions in the CSV row.
_COL_COMPANY_NAME = 1
_COL_LOT_SIZE = 3
_COL_ISIN = 5
_COL_SYMBOL = 9
_COL_IS_MTF_TRADABLE = 19

_ALLOWED_SERIES = {"EQ"}


@dataclass(frozen=True, slots=True)
class ParsedSymbol:
    symbol: str  # e.g. "NSE:RELIANCE-EQ"
    company_name: str
    isin: str | None
    lot_size: int | None
    is_mtf_eligible: bool


@dataclass
class ParseResult:
    symbols: list[ParsedSymbol]
    rows_seen: int
    rows_skipped: int
    skip_reasons_sample: list[str]


def parse_symbol_master_csv(raw_csv: str, max_skip_samples: int = 10) -> ParseResult:
    symbols: list[ParsedSymbol] = []
    rows_seen = 0
    rows_skipped = 0
    skip_reasons_sample: list[str] = []

    def record_skip(reason: str) -> None:
        nonlocal rows_skipped
        rows_skipped += 1
        if len(skip_reasons_sample) < max_skip_samples:
            skip_reasons_sample.append(reason)

    for line in raw_csv.splitlines():
        line = line.strip()
        if not line:
            continue
        rows_seen += 1

        cols = line.split(",")
        if len(cols) < _EXPECTED_MIN_COLUMNS:
            record_skip(f"row has {len(cols)} columns, expected >= {_EXPECTED_MIN_COLUMNS}")
            continue

        symbol_raw = cols[_COL_SYMBOL].strip()
        match = _SYMBOL_RE.match(symbol_raw)
        if not match:
            record_skip(f"symbol column '{symbol_raw}' doesn't match NSE:<TICKER>-<SERIES>")
            continue

        series = match.group(2)
        if series not in _ALLOWED_SERIES:
            continue  # not a skip -- deliberately filtered (e.g. BE/BZ series), not a mapping failure

        company_name = cols[_COL_COMPANY_NAME].strip()
        if not company_name:
            record_skip(f"empty company name for {symbol_raw}")
            continue

        isin_raw = cols[_COL_ISIN].strip()
        isin = isin_raw if _ISIN_RE.match(isin_raw) else None

        try:
            lot_size = int(float(cols[_COL_LOT_SIZE].strip()))
        except (ValueError, IndexError):
            lot_size = None

        is_mtf_eligible = cols[_COL_IS_MTF_TRADABLE].strip() == "1"

        symbols.append(
            ParsedSymbol(
                symbol=symbol_raw,
                company_name=company_name,
                isin=isin,
                lot_size=lot_size,
                is_mtf_eligible=is_mtf_eligible,
            )
        )

    if rows_skipped:
        logger.warning(
            "Symbol master parse: %d/%d rows skipped (validation failures). Sample: %s",
            rows_skipped, rows_seen, skip_reasons_sample,
        )

    return ParseResult(
        symbols=symbols, rows_seen=rows_seen, rows_skipped=rows_skipped, skip_reasons_sample=skip_reasons_sample
    )
