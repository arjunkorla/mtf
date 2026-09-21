"""GET /api/scanner/{symbol}/research-confirmation -- Phase 5 EXPERIMENTAL
research layer, separate from and additive to the existing /api/scanner/*
contract. Reuses scanner.py's own candidate-resolution helpers (import only,
no modification to scanner.py) so this endpoint reflects exactly the same
already-computed CandidateResponse the production scanner/analysis
endpoints return -- never a second, divergent calculation.
"""

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis_dep
from app.api.routes.scanner import _find_universe_entry, _get_candidate_for_confirmation
from app.integrations.fyers.fyers_client import FyersClient
from app.schemas.research import ResearchConfirmation
from app.services.research_confirmation_service import build_research_confirmation_for_candidate

router = APIRouter()


@router.get("/scanner/{symbol}/research-confirmation", response_model=ResearchConfirmation)
async def scanner_research_confirmation(
    symbol: str,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_dep),
) -> ResearchConfirmation:
    entry = _find_universe_entry(symbol)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the configured stock universe")

    candidate = await _get_candidate_for_confirmation(entry, db, redis)

    client = FyersClient()
    try:
        return await build_research_confirmation_for_candidate(candidate, client)
    finally:
        await client.aclose()
