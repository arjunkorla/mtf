"""Parses the NSE bhavcopy CSV (real header row -- see
app/integrations/nse/bhavcopy_client.py) into per-symbol delivery metrics.

Unlike the FYERS symbol-master CSV (undocumented column layout, positional
parsing with defensive validation), this file has genuine column headers,
so parsing is by name, not position -- far less that can silently go wrong.
Still validated: a malformed row (bad numbers, DELIV_PER out of [0, 100])
is skipped and counted rather than trusted.
"""

import csv
import io
from dataclasses import dataclass

from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryMetrics:
    symbol: str  # bare NSE ticker, e.g. "RELIANCE" (no "NSE:"/"-EQ")
    total_traded_qty: int
    delivery_qty: int
    delivery_percentage: float


@dataclass
class BhavcopyParseResult:
    by_symbol: dict[str, DeliveryMetrics]
    rows_seen: int
    rows_skipped: int


def parse_bhavcopy_csv(raw_csv: str) -> BhavcopyParseResult:
    reader = csv.DictReader(io.StringIO(raw_csv), skipinitialspace=True)

    by_symbol: dict[str, DeliveryMetrics] = {}
    rows_seen = 0
    rows_skipped = 0

    for row in reader:
        rows_seen += 1
        try:
            series = (row.get("SERIES") or "").strip()
            if series != "EQ":
                rows_seen -= 1  # not a validation failure -- a deliberate filter, don't count it as "seen" noise
                continue

            symbol = (row.get("SYMBOL") or "").strip()
            deliv_per = float(row["DELIV_PER"])
            deliv_qty = int(float(row["DELIV_QTY"]))
            total_qty = int(float(row["TTL_TRD_QNTY"]))

            if not symbol or not (0.0 <= deliv_per <= 100.0) or deliv_qty < 0 or total_qty < 0:
                rows_skipped += 1
                continue

            by_symbol[symbol] = DeliveryMetrics(
                symbol=symbol, total_traded_qty=total_qty, delivery_qty=deliv_qty, delivery_percentage=deliv_per
            )
        except (KeyError, ValueError, TypeError) as exc:
            rows_skipped += 1
            logger.debug("Skipping malformed bhavcopy row %r: %s", row, exc)

    if rows_skipped:
        logger.warning("Bhavcopy parse: %d/%d EQ rows skipped (validation failures)", rows_skipped, rows_seen)

    return BhavcopyParseResult(by_symbol=by_symbol, rows_seen=rows_seen, rows_skipped=rows_skipped)
