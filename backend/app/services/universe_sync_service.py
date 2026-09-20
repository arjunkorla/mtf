"""Syncs the `stocks` table from the live FYERS NSE symbol master (section 5
follow-up, flagged as a TODO in app/data/universe.py). This is a separate,
explicit maintenance operation -- not wired into the scanner's hot path.

Why not just switch the scanner to read from this table automatically: the
full NSE cash-market universe is ~2000 symbols, and scanning all of them
every run would multiply FYERS API calls (and, against a live broker,
rate-limit exposure -- section 26) by roughly 100x over the 20-stock seed
list with no opt-in from the operator. Run this sync explicitly (see
backend/scripts/sync_universe.py), then update app/data/universe.py or the
scanner's source once you've sized the universe you actually want to scan.

Sector and F&O-eligibility are NOT available from this feed (FYERS'
NSE_CM.csv carries no sector classification, and F&O eligibility would
require cross-referencing NSE_FO.csv's underlying list, not done here) --
synced stocks get sector=None and is_fno=False, which the rest of the
pipeline already treats as an honest "not available" rather than fabricating
a value.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.data.symbol_master_parser import ParsedSymbol, parse_symbol_master_csv
from app.integrations.fyers.symbol_master import fetch_symbol_master_csv
from app.logging_config import get_logger
from app.models.stock import Stock

logger = get_logger(__name__)


@dataclass
class SyncSummary:
    rows_seen: int
    rows_skipped: int
    skip_reasons_sample: list[str]
    inserted: int
    updated: int


async def sync_universe_from_fyers(db: AsyncSession, settings: Settings | None = None) -> SyncSummary:
    settings = settings or get_settings()

    raw_csv = await fetch_symbol_master_csv(settings)
    parsed = parse_symbol_master_csv(raw_csv)

    existing = {s.symbol: s for s in (await db.execute(select(Stock))).scalars().all()}

    inserted = 0
    updated = 0
    for entry in parsed.symbols:
        row = existing.get(entry.symbol)
        if row is None:
            db.add(_new_stock_row(entry))
            inserted += 1
        else:
            if _apply_update(row, entry):
                updated += 1

    await db.commit()

    logger.info(
        "Universe sync complete: seen=%d skipped=%d inserted=%d updated=%d",
        parsed.rows_seen, parsed.rows_skipped, inserted, updated,
    )

    return SyncSummary(
        rows_seen=parsed.rows_seen,
        rows_skipped=parsed.rows_skipped,
        skip_reasons_sample=parsed.skip_reasons_sample,
        inserted=inserted,
        updated=updated,
    )


def _new_stock_row(entry: ParsedSymbol) -> Stock:
    return Stock(
        symbol=entry.symbol,
        exchange="NSE",
        company_name=entry.company_name,
        sector=None,
        is_fno=False,
        is_mtf_eligible=entry.is_mtf_eligible,
        is_liquid=True,
        is_active=True,
        isin=entry.isin,
        lot_size=entry.lot_size,
    )


def _apply_update(row: Stock, entry: ParsedSymbol) -> bool:
    changed = False
    if row.company_name != entry.company_name:
        row.company_name = entry.company_name
        changed = True
    if row.is_mtf_eligible != entry.is_mtf_eligible:
        row.is_mtf_eligible = entry.is_mtf_eligible
        changed = True
    if entry.isin and row.isin != entry.isin:
        row.isin = entry.isin
        changed = True
    if entry.lot_size and row.lot_size != entry.lot_size:
        row.lot_size = entry.lot_size
        changed = True
    if not row.is_active:
        row.is_active = True
        changed = True
    return changed
