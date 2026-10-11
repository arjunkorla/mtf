"""Backfills forward outcomes for previously-persisted ResearchObservations
(Phase 6 Objective 6) once real historical candles exist past each horizon.
Never invents a horizon that hasn't elapsed -- see outcome_engine.py's
module docstring for why "elapsed" is answered by counting real candles,
not calendar arithmetic.
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engines.outcome_engine import OUTCOME_COMPUTED, OUTCOME_PARTIAL, compute_outcome
from app.integrations.fyers.fyers_client import FyersClient
from app.logging_config import get_logger
from app.models.research_observation import ResearchObservation
from app.services.stock_service import _fetch_history

logger = get_logger(__name__)


async def backfill_outcome_for_observation(db: AsyncSession, observation: ResearchObservation, client: FyersClient) -> str:
    all_candles = await _fetch_history(client, observation.symbol)
    future_candles = [c for c in all_candles if c.trade_date > observation.session_date]

    result = compute_outcome(
        observed_price=float(observation.observed_price) if observation.observed_price is not None else None,
        invalidation=float(observation.invalidation) if observation.invalidation is not None else None,
        entry_zone_low=(observation.entry_zone or {}).get("low"),
        entry_zone_high=(observation.entry_zone or {}).get("high"),
        future_candles=future_candles,
    )

    observation.outcome_status = result.status
    observation.next_1d_return = result.next_1d_return
    observation.next_3d_return = result.next_3d_return
    observation.next_5d_return = result.next_5d_return
    observation.next_10d_return = result.next_10d_return
    observation.next_20d_return = result.next_20d_return
    observation.maximum_favorable_excursion = result.maximum_favorable_excursion
    observation.maximum_adverse_excursion = result.maximum_adverse_excursion
    observation.invalidation_hit = result.invalidation_hit
    observation.entry_zone_reached = result.entry_zone_reached
    if result.status in (OUTCOME_COMPUTED, OUTCOME_PARTIAL):
        observation.outcome_computed_at = dt.datetime.now(dt.UTC)

    await db.commit()
    return result.status


async def backfill_pending_outcomes(db: AsyncSession, client: FyersClient, limit: int = 100) -> list[dict]:
    """Never called automatically by this phase's collection path -- outcome
    backfill is a separate, explicit operation (its own route), since it
    makes real FYERS history calls per pending observation and shouldn't
    silently run as a side effect of collecting a new snapshot."""
    pending = (
        await db.execute(
            select(ResearchObservation).where(ResearchObservation.outcome_status != OUTCOME_COMPUTED).limit(limit)
        )
    ).scalars().all()

    results = []
    for observation in pending:
        try:
            status = await backfill_outcome_for_observation(db, observation, client)
        except Exception as exc:  # noqa: BLE001 -- one symbol's history outage must not block the rest of the backfill
            logger.warning("Outcome backfill failed for %s: %s", observation.symbol, exc)
            status = "ERROR"
        results.append({"symbol": observation.symbol, "session_date": observation.session_date.isoformat(), "status": status})
    return results
