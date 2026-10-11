"""Internal diagnostics (Phase 0): FYERS request usage, limiter state and
metering counters. Contains NO tokens, headers, PINs or secrets -- only
counters, configured ceilings and window occupancy."""

from fastapi import APIRouter, Query

from app.integrations.fyers.request_control import usage_snapshot

router = APIRouter()


@router.get("/diagnostics/fyers-usage")
async def fyers_usage(hours: int = Query(default=24, ge=1, le=192)) -> dict:
    return await usage_snapshot(hours=hours)
