"""Tests for app.services.research_snapshot_service (Phase 6 Objectives 1-5,
9). Runs in USE_MOCK_FYERS=true mode via the db_session fixture (real SQLite,
so ResearchMarketSnapshot/ResearchObservation rows are genuinely persisted)
and the test-isolated real Redis client (db 15, see conftest.py).
"""

import datetime as dt

import pytest
from sqlalchemy import select

import app.services.research_snapshot_service as research_snapshot_service
from app.db.redis_client import get_redis
from app.models.research_market_snapshot import ResearchMarketSnapshot
from app.models.research_observation import ResearchObservation
from app.schemas.scanner import ScannerRunRequest
from app.services.research_snapshot_service import collect_research_snapshot, resolve_collection_slot

# No module-level `pytestmark = pytest.mark.asyncio` (see test_redis_isolation.py
# for the same fix): this file mixes two sync tests (resolve_collection_slot,
# pure function) with async ones, and asyncio_mode="auto" already detects
# async tests on its own -- a file-wide mark incorrectly tags the sync ones too.


def _request():
    return ScannerRunRequest(available_capital=100000, risk_percent=1.0, symbols=["NSE:RELIANCE-EQ", "NSE:TCS-EQ"])


def test_resolve_collection_slot_matches_within_tolerance():
    now_ist = dt.datetime(2026, 9, 21, 10, 33, tzinfo=dt.UTC)  # 3 min after 10:30
    assert resolve_collection_slot(now_ist) == "10:30"


def test_resolve_collection_slot_returns_none_outside_any_window():
    now_ist = dt.datetime(2026, 9, 21, 10, 55, tzinfo=dt.UTC)  # well between 10:30 and 11:30
    assert resolve_collection_slot(now_ist) is None


async def test_skips_when_market_closed(db_session, monkeypatch):
    monkeypatch.setattr(research_snapshot_service, "is_market_hours_ist", lambda now_utc=None: False)
    result = await collect_research_snapshot(db_session, get_redis(), _request())
    assert result["status"] == "SKIPPED_NOT_MARKET_HOURS"


async def test_skips_when_not_a_collection_window(db_session, monkeypatch):
    monkeypatch.setattr(research_snapshot_service, "is_market_hours_ist", lambda now_utc=None: True)
    monkeypatch.setattr(research_snapshot_service, "resolve_collection_slot", lambda now_ist, settings=None: None)
    result = await collect_research_snapshot(db_session, get_redis(), _request())
    assert result["status"] == "SKIPPED_NOT_A_COLLECTION_WINDOW"


async def test_collects_and_persists_observations_referencing_one_shared_snapshot(db_session, monkeypatch):
    monkeypatch.setattr(research_snapshot_service, "is_market_hours_ist", lambda now_utc=None: True)
    monkeypatch.setattr(research_snapshot_service, "resolve_collection_slot", lambda now_ist, settings=None: "10:30")

    result = await collect_research_snapshot(db_session, get_redis(), _request())

    assert result["status"] == "COLLECTED"
    assert result["observation_count"] == 2

    snapshots = (await db_session.execute(select(ResearchMarketSnapshot))).scalars().all()
    assert len(snapshots) == 1  # ONE market-wide snapshot, not one per symbol (Objective 9)

    observations = (await db_session.execute(select(ResearchObservation))).scalars().all()
    assert len(observations) == 2
    assert all(o.market_snapshot_id == snapshots[0].id for o in observations)  # shared reference, not duplicated payload
    assert {o.symbol for o in observations} == {"NSE:RELIANCE-EQ", "NSE:TCS-EQ"}
    for o in observations:
        assert o.outcome_status == "OUTCOME_PENDING"  # never fabricated on creation
        assert o.divergence_classification  # always a valid classification, even if INSUFFICIENT_DATA
        assert o.sector_participation


async def test_duplicate_snapshot_prevention_same_slot_same_day(db_session, monkeypatch):
    monkeypatch.setattr(research_snapshot_service, "is_market_hours_ist", lambda now_utc=None: True)
    monkeypatch.setattr(research_snapshot_service, "resolve_collection_slot", lambda now_ist, settings=None: "11:30")

    first = await collect_research_snapshot(db_session, get_redis(), _request())
    assert first["status"] == "COLLECTED"

    second = await collect_research_snapshot(db_session, get_redis(), _request())
    assert second["status"] == "SKIPPED_ALREADY_COLLECTED"
    assert second["snapshot_id"] == first["snapshot_id"]

    snapshots = (await db_session.execute(select(ResearchMarketSnapshot))).scalars().all()
    assert len(snapshots) == 1  # the second call created nothing new
