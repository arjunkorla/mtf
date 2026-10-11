"""Integration tests for the Phase 6 research observation/reporting
endpoints. Runs in USE_MOCK_FYERS=true mode via the app_client fixture."""

import pytest

import app.services.research_snapshot_service as research_snapshot_service

pytestmark = pytest.mark.asyncio


def _scan_body():
    return {"available_capital": 100000, "risk_percent": 1.0, "symbols": ["NSE:RELIANCE-EQ", "NSE:TCS-EQ"]}


async def test_collect_snapshot_skips_outside_market_hours(app_client, monkeypatch):
    monkeypatch.setattr(research_snapshot_service, "is_market_hours_ist", lambda now_utc=None: False)
    resp = await app_client.post("/api/research/collect-snapshot", json=_scan_body())
    assert resp.status_code == 200
    assert resp.json()["status"] == "SKIPPED_NOT_MARKET_HOURS"


async def test_collect_snapshot_then_query_observations(app_client, monkeypatch):
    monkeypatch.setattr(research_snapshot_service, "is_market_hours_ist", lambda now_utc=None: True)
    monkeypatch.setattr(research_snapshot_service, "resolve_collection_slot", lambda now_ist, settings=None: "12:30")

    collect_resp = await app_client.post("/api/research/collect-snapshot", json=_scan_body())
    assert collect_resp.status_code == 200
    assert collect_resp.json()["status"] == "COLLECTED"

    obs_resp = await app_client.get("/api/research/observations")
    assert obs_resp.status_code == 200
    rows = obs_resp.json()
    assert len(rows) == 2
    assert {r["symbol"] for r in rows} == {"NSE:RELIANCE-EQ", "NSE:TCS-EQ"}

    snapshots_resp = await app_client.get("/api/research/snapshots")
    assert len(snapshots_resp.json()) == 1

    detail_resp = await app_client.get(f"/api/research/observations/{rows[0]['id']}")
    assert detail_resp.status_code == 200
    assert "disclaimer" in detail_resp.json()
    assert detail_resp.json()["outcome"]["status"] == "OUTCOME_PENDING"

    divergence_resp = await app_client.get("/api/research/divergence-summary")
    assert divergence_resp.status_code == 200
    total = sum(row["count"] for row in divergence_resp.json())
    assert total == 2


async def test_collected_timestamps_are_the_same_utc_instant(app_client, db_session, monkeypatch):
    """Phase D regression: timestamp_ist used to be now_utc + 5:30 with UTC
    tzinfo attached, persisting an instant 5.5h in the future."""
    import datetime as dt

    from sqlalchemy import select

    from app.models.research_market_snapshot import ResearchMarketSnapshot
    from app.models.research_observation import ResearchObservation

    monkeypatch.setattr(research_snapshot_service, "is_market_hours_ist", lambda now_utc=None: True)
    monkeypatch.setattr(research_snapshot_service, "resolve_collection_slot", lambda now_ist, settings=None: "14:30")
    assert (await app_client.post("/api/research/collect-snapshot", json=_scan_body())).json()["status"] == "COLLECTED"

    def utc(ts):  # SQLite drops tzinfo; persisted values are UTC
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.UTC)

    snap = (await db_session.execute(select(ResearchMarketSnapshot))).scalars().one()
    assert utc(snap.timestamp_ist) == utc(snap.timestamp_utc)
    for obs in (await db_session.execute(select(ResearchObservation))).scalars():
        assert utc(obs.timestamp_ist) == utc(obs.timestamp_utc)


async def test_collection_clock_returns_one_instant_with_ist_wall_time():
    import datetime as dt

    now_utc, now_ist = research_snapshot_service.collection_clock(dt.datetime(2026, 9, 29, 4, 50, 41, tzinfo=dt.UTC))
    assert now_ist == now_utc  # same instant
    assert now_ist.utcoffset() == dt.timedelta(hours=5, minutes=30) and (now_ist.hour, now_ist.minute) == (10, 20)
    assert research_snapshot_service.resolve_collection_slot(now_ist) == "10:30"  # slot logic uses IST wall time


async def test_collect_snapshot_twice_same_slot_is_idempotent(app_client, monkeypatch):
    monkeypatch.setattr(research_snapshot_service, "is_market_hours_ist", lambda now_utc=None: True)
    monkeypatch.setattr(research_snapshot_service, "resolve_collection_slot", lambda now_ist, settings=None: "13:30")

    first = await app_client.post("/api/research/collect-snapshot", json=_scan_body())
    second = await app_client.post("/api/research/collect-snapshot", json=_scan_body())

    assert first.json()["status"] == "COLLECTED"
    assert second.json()["status"] == "SKIPPED_ALREADY_COLLECTED"

    obs_resp = await app_client.get("/api/research/observations")
    assert len(obs_resp.json()) == 2  # not 4 -- the duplicate attempt created nothing


async def test_observation_not_found_returns_404(app_client):
    resp = await app_client.get("/api/research/observations/999999")
    assert resp.status_code == 404


async def test_this_layer_never_appears_in_production_scanner_contract(app_client):
    resp = await app_client.post("/api/scanner/run", json=_scan_body())
    assert resp.status_code == 200
    body = resp.json()
    assert "research_observations" not in body
    assert "divergence_classification" not in str(body.get("candidates", [{}])[0].keys() if body.get("candidates") else {})
