"""POST /api/scanner/run, GET /api/scanner/results,
GET /api/scanner/{symbol}/realtime-confirmation"""

from fastapi import APIRouter, Depends, HTTPException, Query
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis_dep
from app.data.universe import get_seed_universe
from app.integrations.fyers.fyers_client import FyersClient
from app.schemas.confirmation import RealtimeConfirmationResponse
from app.schemas.scanner import CandidateResponse, ScannerResultsResponse, ScannerRunRequest, ScannerRunResponse
from app.schemas.settings import ScannerSettings
from app.services.cache_service import (
    TTL_ANALYSIS_SECONDS,
    TTL_SCANNER_RESULTS_SECONDS,
    analysis_key,
    get_json,
    scanner_results_key,
    set_json,
)
from app.services.realtime_confirmation_service import get_realtime_confirmation
from app.services.scanner_service import get_scanner_results, run_scanner
from app.services.settings_service import get_scanner_settings
from app.services.stock_service import CandidateRejected, build_candidate, get_nifty_candles, load_stock_context

router = APIRouter()


def _find_universe_entry(symbol: str):
    normalized = symbol.upper()
    for entry in get_seed_universe():
        if entry.symbol.upper() == normalized or entry.symbol.split(":")[-1].split("-")[0] == normalized:
            return entry
    return None


async def _get_candidate_for_confirmation(
    entry, db: AsyncSession, redis: Redis,
) -> CandidateResponse:
    """Reuses the same cache /stocks/{symbol}/analysis already populates
    (analysis_key) rather than recomputing technical/volume/fno calculations
    here -- this only orchestrates, it never duplicates an engine."""
    cached = await get_json(redis, analysis_key(entry.symbol))
    if cached is not None and cached.get("candidate") is not None:
        return CandidateResponse.model_validate(cached["candidate"])

    client = FyersClient()
    try:
        nifty_candles = await get_nifty_candles(client)
        context = await load_stock_context(client, db, entry, nifty_candles)
        try:
            return await build_candidate(client, entry, context, ScannerSettings())
        except CandidateRejected as exc:
            raise HTTPException(status_code=422, detail=f"{entry.symbol} failed candidate filters: {exc.reason}")
    finally:
        await client.aclose()


@router.post("/scanner/run", response_model=ScannerRunResponse)
async def scanner_run(
    request: ScannerRunRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_dep),
) -> ScannerRunResponse:
    settings = await get_scanner_settings(redis)
    return await run_scanner(request, db, settings)


@router.get("/scanner/results", response_model=ScannerResultsResponse)
async def scanner_results(
    run_id: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_dep),
) -> ScannerResultsResponse:
    # "latest completed run" (run_id=None) is cached under its own key so it
    # doesn't collide with a specific run_id's cache entry.
    cache_key = scanner_results_key(run_id if run_id is not None else 0)
    cached = await get_json(redis, cache_key)
    if cached is not None:
        return ScannerResultsResponse.model_validate(cached)

    result = await get_scanner_results(db, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No scanner run found")

    await set_json(redis, cache_key, result.model_dump(mode="json"), TTL_SCANNER_RESULTS_SECONDS)
    return result


@router.get("/scanner/{symbol}/realtime-confirmation", response_model=RealtimeConfirmationResponse)
async def scanner_realtime_confirmation(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_dep),
) -> RealtimeConfirmationResponse:
    """Real-Time Confirmation Engine (section: realtime confirmation) --
    evidence-based intraday confirmation for one candidate's existing MTF
    setup. Never affects scanner_run's ranking/selection: this is a
    separate, on-demand read, not part of the scan pipeline."""
    entry = _find_universe_entry(symbol)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the configured stock universe")

    candidate = await _get_candidate_for_confirmation(entry, db, redis)

    client = FyersClient()
    try:
        return await get_realtime_confirmation(entry.symbol, candidate, client)
    finally:
        await client.aclose()
