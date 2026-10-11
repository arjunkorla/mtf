"""Tests for app.services.outcome_service (Phase 6 Objective 6). Uses
USE_MOCK_FYERS=true's deterministic mock daily history (see
app/integrations/fyers/mock_responses.py's mock_history_response), which
always spans up to "today" -- so an observation dated far enough in the
past has genuine "future" mock candles after it, without needing real
elapsed wall-clock time.
"""

import datetime as dt

import pytest
from sqlalchemy import select

from app.engines.outcome_engine import OUTCOME_COMPUTED, OUTCOME_PARTIAL, OUTCOME_PENDING
from app.integrations.fyers.fyers_client import FyersClient
from app.models.research_market_snapshot import ResearchMarketSnapshot
from app.models.research_observation import ResearchObservation
from app.services.outcome_service import backfill_outcome_for_observation, backfill_pending_outcomes

pytestmark = pytest.mark.asyncio


async def _make_snapshot(db_session) -> int:
    snapshot = ResearchMarketSnapshot(
        session_date=dt.date.today(), timestamp_utc=dt.datetime.now(dt.UTC), timestamp_ist=dt.datetime.now(dt.UTC),
        slot_label="10:30", nifty_regime="NEUTRAL", india_vix=None, vix_regime="INSUFFICIENT_DATA",
        global_risk_sentiment="INSUFFICIENT_DATA", global_macro_payload={},
    )
    db_session.add(snapshot)
    await db_session.flush()
    return snapshot.id


def _make_observation(snapshot_id: int, session_date: dt.date, symbol="NSE:RELIANCE-EQ") -> ResearchObservation:
    return ResearchObservation(
        session_date=session_date, timestamp_utc=dt.datetime.now(dt.UTC), timestamp_ist=dt.datetime.now(dt.UTC),
        symbol=symbol, market_snapshot_id=snapshot_id, observed_price=100.0,
        mtf_score=50.0, research_status="NEUTRAL", sector_participation="INSUFFICIENT_DATA",
        divergence_classification="INSUFFICIENT_DATA", invalidation=90.0,
        entry_zone={"low": 95.0, "high": 100.0}, payload={},
    )


async def test_stays_pending_when_no_future_candles_exist_yet(db_session):
    snapshot_id = await _make_snapshot(db_session)
    observation = _make_observation(snapshot_id, session_date=dt.date.today())  # "today" -- no future candles exist
    db_session.add(observation)
    await db_session.flush()

    client = FyersClient()
    try:
        status = await backfill_outcome_for_observation(db_session, observation, client)
    finally:
        await client.aclose()

    assert status == OUTCOME_PENDING
    assert observation.next_1d_return is None
    assert observation.outcome_computed_at is None


async def test_computes_outcome_once_real_future_candles_exist(db_session):
    snapshot_id = await _make_snapshot(db_session)
    old_date = dt.date.today() - dt.timedelta(days=30)  # mock history's ~320-day window has real "future" candles past this
    observation = _make_observation(snapshot_id, session_date=old_date)
    db_session.add(observation)
    await db_session.flush()

    client = FyersClient()
    try:
        status = await backfill_outcome_for_observation(db_session, observation, client)
    finally:
        await client.aclose()

    assert status in (OUTCOME_PARTIAL, OUTCOME_COMPUTED)
    assert observation.next_1d_return is not None
    assert observation.outcome_computed_at is not None


async def test_backfill_pending_outcomes_processes_multiple_and_skips_errors(db_session, monkeypatch):
    snapshot_id = await _make_snapshot(db_session)
    old_date = dt.date.today() - dt.timedelta(days=30)
    obs1 = _make_observation(snapshot_id, old_date, symbol="NSE:RELIANCE-EQ")
    obs2 = _make_observation(snapshot_id, old_date, symbol="NSE:BADSYMBOL-EQ")
    db_session.add_all([obs1, obs2])
    await db_session.flush()

    import app.services.stock_service as stock_service

    original_fetch = stock_service._fetch_history

    async def _flaky_fetch(client, symbol, days=320):
        if symbol == "NSE:BADSYMBOL-EQ":
            raise RuntimeError("simulated history outage")
        return await original_fetch(client, symbol, days)

    monkeypatch.setattr("app.services.outcome_service._fetch_history", _flaky_fetch)

    client = FyersClient()
    try:
        results = await backfill_pending_outcomes(db_session, client, limit=10)
    finally:
        await client.aclose()

    by_symbol = {r["symbol"]: r["status"] for r in results}
    assert by_symbol["NSE:RELIANCE-EQ"] in (OUTCOME_PARTIAL, OUTCOME_COMPUTED)
    assert by_symbol["NSE:BADSYMBOL-EQ"] == "ERROR"


async def test_backfill_pending_outcomes_excludes_already_computed(db_session):
    snapshot_id = await _make_snapshot(db_session)
    obs = _make_observation(snapshot_id, dt.date.today() - dt.timedelta(days=30))
    obs.outcome_status = OUTCOME_COMPUTED
    db_session.add(obs)
    await db_session.flush()

    client = FyersClient()
    try:
        results = await backfill_pending_outcomes(db_session, client, limit=10)
    finally:
        await client.aclose()

    assert results == []
