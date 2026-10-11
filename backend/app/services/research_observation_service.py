"""Read-only queries for persisted research observations/snapshots (Phase 6
Objective 12 reporting). Research-only -- never used by the production
scanner or scoring path.
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.research_market_snapshot import ResearchMarketSnapshot
from app.models.research_observation import ResearchObservation


async def list_observations(
    db: AsyncSession, session_date: dt.date | None = None, symbol: str | None = None, limit: int = 200,
) -> list[ResearchObservation]:
    stmt = select(ResearchObservation).order_by(ResearchObservation.timestamp_utc.desc()).limit(limit)
    if session_date is not None:
        stmt = stmt.where(ResearchObservation.session_date == session_date)
    if symbol is not None:
        stmt = stmt.where(ResearchObservation.symbol == symbol)
    return list((await db.execute(stmt)).scalars().all())


async def get_observation(db: AsyncSession, observation_id: int) -> ResearchObservation | None:
    return await db.get(ResearchObservation, observation_id)


async def list_snapshots(db: AsyncSession, session_date: dt.date | None = None, limit: int = 50) -> list[ResearchMarketSnapshot]:
    stmt = select(ResearchMarketSnapshot).order_by(ResearchMarketSnapshot.timestamp_utc.desc()).limit(limit)
    if session_date is not None:
        stmt = stmt.where(ResearchMarketSnapshot.session_date == session_date)
    return list((await db.execute(stmt)).scalars().all())


async def divergence_summary(db: AsyncSession, session_date: dt.date | None = None) -> list[dict]:
    stmt = select(ResearchObservation)
    if session_date is not None:
        stmt = stmt.where(ResearchObservation.session_date == session_date)
    rows = (await db.execute(stmt)).scalars().all()

    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(row.divergence_classification, []).append(row.symbol)

    return [{"classification": k, "count": len(v), "symbols": v} for k, v in grouped.items()]
