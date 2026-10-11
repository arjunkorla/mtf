"""Read-only suggestion history / tracking API (Phase B).

There is deliberately NO create/update/delete endpoint: suggestions originate
only from approved scanner adapters inside the backend. Every endpoint here
reads PostgreSQL (plus the tracker's in-process status / Redis live view)
and never triggers a FYERS request.
"""

import datetime as dt
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis_dep
from app.schemas.suggestion import (
    SuggestionDetailResponse,
    SuggestionEventResponse,
    SuggestionListItem,
    SuggestionListResponse,
)
from app.services import suggestion_analytics_service as analytics_svc
from app.services import suggestion_service as svc
from app.services.cache_service import get_json
from app.services.suggestion_tracker_service import get_suggestion_tracker, live_view_key

router = APIRouter()

DEFAULT_WINDOW = dt.timedelta(days=7)
MEASUREMENT_DISCLAIMER = (
    "Research measurement only. Outcomes are tracked against genuine FYERS market data to discover "
    "whether the scanner works -- not evidence that it does. Small samples are not conclusive."
)

# Evidence snapshots are scanner features, but never let anything that looks
# like a credential leave the API even if a future adapter stores one.
_SECRET_KEY = re.compile(
    r"token|secret|passw(or)?d|authorization|api[_-]?key|cookie|client[_-]?id|(^|_)pin($|_)", re.IGNORECASE
)


def _redact(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if _SECRET_KEY.search(str(k)) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _utc(ts: dt.datetime | None) -> dt.datetime | None:
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.UTC)


def _filters(
    scanner: str | None, market: str | None, status: list[str] | None, outcome: list[str] | None,
    symbol: str | None, direction: str | None, generated_from: dt.datetime | None, generated_to: dt.datetime | None,
) -> svc.SuggestionFilters:
    return svc.SuggestionFilters(
        scanner_type=scanner.upper() if scanner else None, market=market,
        status=[s.upper() for s in status] if status else None,
        outcome=[o.upper() for o in outcome] if outcome else None,
        symbol=symbol, direction=direction.upper() if direction else None,
        generated_from=_utc(generated_from), generated_to=_utc(generated_to),
    )


@router.get("/suggestions/performance")
async def suggestion_performance(
    scanner: str | None = Query(default=None),
    market: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    generated_from: dt.datetime | None = Query(default=None, alias="from"),
    generated_to: dt.datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregates over ALL matching suggestions (no implicit 7-day window --
    that would silently shrink the sample). Win rate denominator =
    triggered trades that reached a market-determined terminal outcome."""
    filters = _filters(scanner, market, None, None, symbol, direction, generated_from, generated_to)
    summary = await svc.performance_summary(db, filters)
    return {
        **summary,
        "sample_status": "NO_COMPLETED_TRADES" if summary["sample_size"] == 0 else "REPORTED_WITH_SAMPLE_SIZE",
        "window": {"from": filters.generated_from, "to": filters.generated_to},
        "methodology": {
            "win_rate_denominator": "entry triggered AND terminal outcome in "
                                    + ", ".join(sorted(svc.COMPLETED_TRADE_OUTCOMES)),
            "wins": sorted(svc.WIN_OUTCOMES),
            "losses": sorted(svc.LOSS_OUTCOMES),
            "partial_success": "target 1 reached, then the ORIGINAL stop (reported separately)",
            "expired_without_target": "counted in the denominator, neither win nor loss",
            "excluded_from_win_rate": ["NO_ENTRY", "INVALIDATED_BEFORE_ENTRY", "CANCELLED", "open suggestions"],
            "ambiguous_bars": "same-bar stop+target resolved stop-first unless ordered ticks proved otherwise",
            "confidence_interval": "95% Wilson score interval on the win rate",
            "minimum_sample_threshold": None,
            "note": "No statistical-significance threshold is configured; judge the sample size and interval.",
        },
        "disclaimer": MEASUREMENT_DISCLAIMER,
    }


@router.get("/suggestions/tracker/status")
async def tracker_status() -> dict:
    """In-process tracker state/metrics. Makes no FYERS call."""
    return get_suggestion_tracker().status_snapshot()


@router.get("/suggestions/analysis-dataset")
async def suggestion_analysis_dataset(
    scanner: str | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    outcome: list[str] | None = Query(default=None),
    symbol: str | None = Query(default=None),
    generated_from: dt.datetime | None = Query(default=None, alias="from"),
    generated_to: dt.datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Flat research rows (generation-time features + tracked outcome). All
    history by default -- nothing is windowed away or deleted."""
    filters = _filters(scanner, None, status, outcome, symbol, None, generated_from, generated_to)
    rows, total = await analytics_svc.dataset(db, filters, limit, offset)
    return {"rows": rows, "total": total, "limit": limit, "offset": offset,
            "note": "Features are generation-time snapshot values only; no later data is back-filled.",
            "disclaimer": MEASUREMENT_DISCLAIMER}


@router.get("/suggestions/analytics")
async def suggestion_analytics(
    scanner: str | None = Query(default=None),
    generated_from: dt.datetime | None = Query(default=None, alias="from"),
    generated_to: dt.datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Descriptive statistics over ALL matching suggestions (no implicit
    window). Reads PostgreSQL only."""
    from sqlalchemy import select

    from app.models.mtf_collection_run import MtfCollectionRun

    filters = _filters(scanner, None, None, None, None, None, generated_from, generated_to)
    rows, _ = await analytics_svc.dataset(db, filters)
    runs = list((await db.execute(select(MtfCollectionRun))).scalars().all())
    return {**analytics_svc.analytics(rows, runs), "disclaimer": MEASUREMENT_DISCLAIMER}


@router.get("/suggestions/segments")
async def suggestion_segments(
    by: str = Query(..., description="one of: " + ", ".join(sorted(analytics_svc.SEGMENTS))),
    scanner: str | None = Query(default=None),
    generated_from: dt.datetime | None = Query(default=None, alias="from"),
    generated_to: dt.datetime | None = Query(default=None, alias="to"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if by not in analytics_svc.SEGMENTS:
        raise HTTPException(status_code=422, detail=f"unknown segment {by!r}; use one of {sorted(analytics_svc.SEGMENTS)}")
    filters = _filters(scanner, None, None, None, None, None, generated_from, generated_to)
    rows, _ = await analytics_svc.dataset(db, filters)
    return {**analytics_svc.segments(rows, by), "disclaimer": MEASUREMENT_DISCLAIMER}


@router.get("/suggestions/collection/status")
async def collection_status(db: AsyncSession = Depends(get_db)) -> dict:
    from app.services.mtf_daily_collection_service import get_daily_collector

    return await get_daily_collector().status(db)


@router.get("/suggestions/collection/runs")
async def collection_runs(limit: int = Query(default=50, ge=1, le=500), db: AsyncSession = Depends(get_db)) -> list[dict]:
    from sqlalchemy import select

    from app.models.mtf_collection_run import MtfCollectionRun
    from app.services.mtf_daily_collection_service import run_dict

    rows = (await db.execute(select(MtfCollectionRun).order_by(MtfCollectionRun.id.desc()).limit(limit))).scalars().all()
    return [{**run_dict(r), "summary": r.summary} for r in rows]


@router.get("/suggestions/adapter/last-run")
async def adapter_last_run() -> dict:
    """Most recent MTF adapter evaluation in this process (dry-run or
    persist). In-memory only; makes no FYERS call."""
    from app.config import get_settings
    from app.services.mtf_suggestion_adapter import adapter_mode, last_run

    return {"mode": adapter_mode(get_settings()), "last_run": last_run()}


@router.get("/suggestions", response_model=SuggestionListResponse)
async def list_suggestions(
    scanner: str | None = Query(default=None),
    market: str | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    outcome: list[str] | None = Query(default=None),
    symbol: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    generated_from: dt.datetime | None = Query(default=None, alias="from"),
    generated_to: dt.datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> SuggestionListResponse:
    """History. Defaults to the last 7 days of generation time -- a QUERY
    default only; older rows are kept forever and reachable with `from`."""
    defaulted = generated_from is None and generated_to is None
    if defaulted:
        generated_from = dt.datetime.now(dt.UTC) - DEFAULT_WINDOW
    filters = _filters(scanner, market, status, outcome, symbol, direction, generated_from, generated_to)
    rows, total = await svc.query_suggestions(db, filters, limit, offset)
    return SuggestionListResponse(
        items=[SuggestionListItem.model_validate(r) for r in rows], total=total, limit=limit, offset=offset,
        window={"from": filters.generated_from, "to": filters.generated_to, "defaulted_to_last_7_days": defaulted},
    )


@router.get("/suggestions/{suggestion_id}", response_model=SuggestionDetailResponse)
async def get_suggestion(
    suggestion_id: int, db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis_dep),
) -> SuggestionDetailResponse:
    row = await svc.get_suggestion(db, suggestion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    detail = SuggestionDetailResponse.model_validate(row)
    detail.evidence_snapshot = _redact(detail.evidence_snapshot)
    detail.research_metadata = _redact(detail.research_metadata)
    detail.provisional_live = await get_json(redis, live_view_key(suggestion_id))
    detail.disclaimer = MEASUREMENT_DISCLAIMER
    return detail


@router.get("/suggestions/{suggestion_id}/events", response_model=list[SuggestionEventResponse])
async def get_suggestion_events(suggestion_id: int, db: AsyncSession = Depends(get_db)) -> list[SuggestionEventResponse]:
    if await svc.get_suggestion(db, suggestion_id) is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return [SuggestionEventResponse.model_validate(e) for e in await svc.list_events(db, suggestion_id)]
