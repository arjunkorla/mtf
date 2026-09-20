import datetime as dt

import pytest

from app.integrations.fyers.fyers_client import FyersClient
from app.models.stock import Stock
from app.services.walk_forward_service import run_walk_forward_validation

pytestmark = pytest.mark.asyncio


async def test_walk_forward_runs_multiple_windows_and_aggregates(db_session):
    stock = Stock(symbol="NSE:RELIANCE-EQ", company_name="Reliance Industries Ltd", sector="Energy", is_mtf_eligible=True)
    db_session.add(stock)
    await db_session.flush()

    client = FyersClient()
    try:
        report = await run_walk_forward_validation(
            client, db_session, "NSE:RELIANCE-EQ", "Energy",
            overall_start=dt.date.today() - dt.timedelta(days=200),
            overall_end=dt.date.today() - dt.timedelta(days=20),
            window_days=60,
            holding_period_days=10,
        )
    finally:
        await client.aclose()

    assert report.symbol == "NSE:RELIANCE-EQ"
    assert len(report.windows) >= 2
    # Windows are sequential and non-overlapping by default (step == window_days).
    for i in range(1, len(report.windows)):
        assert report.windows[i].start_date == report.windows[i - 1].end_date

    assert len(report.hit_rate_by_window) == len(report.windows)
    assert report.combined is not None
    assert report.combined.count == sum(len(w.summary.trades) for w in report.windows)


async def test_walk_forward_rejects_when_no_window_fits(db_session):
    client = FyersClient()
    try:
        with pytest.raises(ValueError):
            await run_walk_forward_validation(
                client, db_session, "NSE:RELIANCE-EQ", None,
                overall_start=dt.date.today() - dt.timedelta(days=10),
                overall_end=dt.date.today() - dt.timedelta(days=5),
                window_days=90,
            )
    finally:
        await client.aclose()


async def test_walk_forward_custom_step_produces_overlapping_windows(db_session):
    client = FyersClient()
    try:
        report = await run_walk_forward_validation(
            client, db_session, "NSE:RELIANCE-EQ", None,
            overall_start=dt.date.today() - dt.timedelta(days=200),
            overall_end=dt.date.today() - dt.timedelta(days=20),
            window_days=60,
            step_days=30,
            holding_period_days=10,
            persist_signals=False,
        )
    finally:
        await client.aclose()

    assert len(report.windows) >= 2
    # Overlapping: window 1 starts before window 0 ends.
    assert report.windows[1].start_date < report.windows[0].end_date
