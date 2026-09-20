import datetime as dt

import pytest
from sqlalchemy import select

from app.integrations.fyers.fyers_client import FyersClient
from app.models.signal import Signal
from app.models.stock import Stock
from app.services.backtest_service import run_backtest

pytestmark = pytest.mark.asyncio


async def test_backtest_generates_and_persists_signals(db_session):
    stock = Stock(symbol="NSE:RELIANCE-EQ", company_name="Reliance Industries Ltd", sector="Energy", is_mtf_eligible=True)
    db_session.add(stock)
    await db_session.flush()

    client = FyersClient()
    try:
        summary = await run_backtest(
            client, db_session, "NSE:RELIANCE-EQ", "Energy",
            start_date=dt.date.today() - dt.timedelta(days=60),
            end_date=dt.date.today() - dt.timedelta(days=30),
            holding_period_days=10,
        )
    finally:
        await client.aclose()

    assert summary.symbol == "NSE:RELIANCE-EQ"
    assert summary.signals_generated > 0

    rows = (await db_session.execute(select(Signal).where(Signal.stock_id == stock.id))).scalars().all()
    assert len(rows) == summary.signals_generated
    for row in rows:
        assert row.total_score is not None
        assert row.institutional_footprint_level in ("STRONG", "MODERATE", "WEAK", "NEUTRAL", "INSUFFICIENT_DATA")


async def test_backtest_without_stock_row_still_returns_results(db_session):
    """A symbol not yet in the stocks table can still be backtested -- it
    just won't have anywhere to persist signals."""
    client = FyersClient()
    try:
        summary = await run_backtest(
            client, db_session, "NSE:UNKNOWN-EQ", None,
            start_date=dt.date.today() - dt.timedelta(days=60),
            end_date=dt.date.today() - dt.timedelta(days=30),
            holding_period_days=10,
        )
    finally:
        await client.aclose()

    assert summary.signals_generated > 0
    rows = (await db_session.execute(select(Signal))).scalars().all()
    assert rows == []


async def test_backtest_rejects_invalid_date_range(db_session):
    client = FyersClient()
    try:
        with pytest.raises(ValueError):
            await run_backtest(
                client, db_session, "NSE:RELIANCE-EQ", None,
                start_date=dt.date.today(),
                end_date=dt.date.today() - dt.timedelta(days=1),
            )
    finally:
        await client.aclose()
