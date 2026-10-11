"""Research observation collection + reporting endpoints (Phase 6).
Research-only: never exposed as production trading advice, never part of
the existing /api/scanner/* contract.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis_dep
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.request_control import RequestPriority, fyers_priority
from app.schemas.research import (
    CollectionResult,
    DivergenceSummaryRow,
    ResearchMarketSnapshotSummary,
    ResearchObservationSummary,
)
from app.schemas.scanner import ScannerRunRequest
from app.services import research_observation_service
from app.services.outcome_service import backfill_pending_outcomes
from app.services.research_snapshot_service import collect_research_snapshot

router = APIRouter()

RESEARCH_ONLY_DISCLAIMER = (
    "Research-only diagnostic data for evaluating the EXPERIMENTAL Research Confirmation "
    "layer against the production MTF score. Not trading advice; production ranking is "
    "based solely on the existing scanner/scoring_engine.py, unaffected by this data."
)


@router.post("/research/collect-snapshot", response_model=CollectionResult)
async def collect_snapshot(
    request: ScannerRunRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_dep),
) -> CollectionResult:
    """Runs the real, unmodified scanner and persists one observation set --
    but only during real NSE market hours, at a configured slot (within
    tolerance), and at most once per (session_date, slot). Never fabricates
    a collection outside those conditions -- see CollectionResult.status."""
    # Research collection is background work: it runs under a lower
    # FYERS request-budget tier so it can never starve user-requested scans
    # or active-suggestion risk checks (see request_control.py).
    with fyers_priority(RequestPriority.BACKGROUND):
        result = await collect_research_snapshot(db, redis, request)
    return CollectionResult(**result)


@router.post("/research/backfill-outcomes")
async def backfill_outcomes(
    limit: int = Query(default=100, le=500), db: AsyncSession = Depends(get_db)
) -> dict:
    client = FyersClient(priority=RequestPriority.BACKGROUND)
    try:
        results = await backfill_pending_outcomes(db, client, limit=limit)
    finally:
        await client.aclose()
    return {"disclaimer": RESEARCH_ONLY_DISCLAIMER, "results": results}


@router.get("/research/observations", response_model=list[ResearchObservationSummary])
async def get_observations(
    session_date: dt.date | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=200, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[ResearchObservationSummary]:
    rows = await research_observation_service.list_observations(db, session_date, symbol, limit)
    return [ResearchObservationSummary.model_validate(row, from_attributes=True) for row in rows]


@router.get("/research/observations/{observation_id}")
async def get_observation_detail(observation_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    row = await research_observation_service.get_observation(db, observation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Observation not found")

    return {
        "disclaimer": RESEARCH_ONLY_DISCLAIMER,
        "id": row.id,
        "payload": row.payload,
        "sector_participation": row.sector_participation,
        "sector_participation_evidence": row.sector_participation_evidence,
        "divergence": {
            "research_minus_mtf": row.research_minus_mtf,
            "research_rank_minus_mtf_rank": row.research_rank_minus_mtf_rank,
            "classification": row.divergence_classification,
        },
        "outcome": {
            "status": row.outcome_status,
            "next_1d_return": row.next_1d_return,
            "next_3d_return": row.next_3d_return,
            "next_5d_return": row.next_5d_return,
            "next_10d_return": row.next_10d_return,
            "next_20d_return": row.next_20d_return,
            "maximum_favorable_excursion": row.maximum_favorable_excursion,
            "maximum_adverse_excursion": row.maximum_adverse_excursion,
            "invalidation_hit": row.invalidation_hit,
            "entry_zone_reached": row.entry_zone_reached,
        },
        "live_confirmation_coverage": row.live_confirmation_coverage,
        "research_data_coverage": row.research_data_coverage,
    }


@router.get("/research/snapshots", response_model=list[ResearchMarketSnapshotSummary])
async def get_snapshots(
    session_date: dt.date | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[ResearchMarketSnapshotSummary]:
    rows = await research_observation_service.list_snapshots(db, session_date, limit)
    return [ResearchMarketSnapshotSummary.model_validate(row, from_attributes=True) for row in rows]


@router.get("/research/divergence-summary", response_model=list[DivergenceSummaryRow])
async def get_divergence_summary(
    session_date: dt.date | None = Query(default=None), db: AsyncSession = Depends(get_db),
) -> list[DivergenceSummaryRow]:
    rows = await research_observation_service.divergence_summary(db, session_date)
    return [DivergenceSummaryRow(**row) for row in rows]
