import pytest
from sqlalchemy import select

from app.models.stock import Stock
from app.services.universe_sync_service import sync_universe_from_fyers

pytestmark = pytest.mark.asyncio


async def test_sync_inserts_mock_symbols(db_session):
    summary = await sync_universe_from_fyers(db_session)

    # The mock CSV has 4 rows: 3 EQ series (one is_mtf_eligible=0) + 1 BE
    # series that's deliberately filtered, not inserted.
    assert summary.rows_skipped == 0
    assert summary.inserted == 3

    rows = (await db_session.execute(select(Stock))).scalars().all()
    symbols = {r.symbol for r in rows}
    assert "NSE:20MICRONS-EQ" in symbols
    assert "NSE:3IINFOLTD-BE" not in symbols  # BE series filtered

    twenty_microns = next(r for r in rows if r.symbol == "NSE:20MICRONS-EQ")
    assert twenty_microns.company_name == "20 MICRONS LTD"
    assert twenty_microns.isin == "INE144J01027"
    assert twenty_microns.is_mtf_eligible is True
    assert twenty_microns.sector is None  # honest gap: not available from this feed
    assert twenty_microns.is_fno is False  # honest gap: requires NSE_FO.csv cross-reference


async def test_sync_is_idempotent_on_rerun(db_session):
    first = await sync_universe_from_fyers(db_session)
    second = await sync_universe_from_fyers(db_session)

    assert first.inserted == 3
    assert second.inserted == 0  # already exist, no duplicates
    assert second.updated == 0  # nothing changed between runs

    rows = (await db_session.execute(select(Stock))).scalars().all()
    assert len(rows) == 3
