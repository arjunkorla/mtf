"""One symbol's research observation at one collection slot (Phase 6).

Never stores API secrets. References ResearchMarketSnapshot for market-wide
context (India VIX, global macro, NIFTY regime) instead of duplicating it
per row (Objective 9). `payload` carries the full ResearchConfirmation
response for zero-information-loss replay; the explicit columns alongside it
exist so the reporting endpoint (Objective 12) can filter/aggregate without
deserializing JSON for every query -- same pattern as the existing
ScannerResult model (rank/score/signal_quality columns + a full `payload`).

Outcome columns (next_Nd_return, MFE/MAE, invalidation_hit, entry_zone_reached)
start out NULL with outcome_status="OUTCOME_PENDING" and are only ever filled
in by outcome_engine.py once real historical candles exist past the horizon
-- never fabricated, never backdated.
"""

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchObservation(Base):
    __tablename__ = "research_observations"
    __table_args__ = (
        # One observation per symbol per market snapshot -- the DB-level
        # guarantee behind "duplicate snapshot prevention" (Objective 13).
        UniqueConstraint("market_snapshot_id", "symbol", name="uq_research_observation_snapshot_symbol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    session_date: Mapped[dt.date] = mapped_column(Date, index=True)
    timestamp_utc: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    timestamp_ist: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))  # derived display value
    symbol: Mapped[str] = mapped_column(String(32), index=True)

    market_snapshot_id: Mapped[int] = mapped_column(ForeignKey("research_market_snapshots.id", ondelete="CASCADE"), index=True)

    observed_price: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)

    mtf_score: Mapped[float] = mapped_column(Numeric(6, 2))
    mtf_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    research_confirmation_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    research_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    research_status: Mapped[str] = mapped_column(String(32))

    technical_state: Mapped[str | None] = mapped_column(String(64), nullable=True)  # "STRONG_DOWNTREND / NO_BREAKOUT"

    stock_return_5d: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    stock_return_20d: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)

    sector: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sector_state: Mapped[str | None] = mapped_column(String(32), nullable=True)  # sector_strength_label
    sector_return_5d: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    sector_return_20d: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)

    stock_vs_sector_5d: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    stock_vs_sector_20d: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    stock_vs_nifty_5d: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    stock_vs_nifty_20d: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)

    # Phase 6 Objective 4 -- analytical only, never fed back into scoring.
    sector_participation: Mapped[str] = mapped_column(String(32))  # SectorParticipation
    sector_participation_evidence: Mapped[dict] = mapped_column(JSON, default=dict)

    volume_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    institutional_proxy: Mapped[str | None] = mapped_column(String(32), nullable=True)

    futures_state: Mapped[str | None] = mapped_column(String(32), nullable=True)  # positioning_proxy
    futures_oi_context: Mapped[dict] = mapped_column(JSON, default=dict)
    options_context: Mapped[dict] = mapped_column(JSON, default=dict)

    live_confirmation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    live_confirmation_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    market_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)  # pass-through from the snapshot, for convenient filtering

    news_context: Mapped[dict] = mapped_column(JSON, default=dict)
    corporate_event_context: Mapped[dict] = mapped_column(JSON, default=dict)

    supporting_signals: Mapped[list] = mapped_column(JSON, default=list)
    conflicting_signals: Mapped[list] = mapped_column(JSON, default=list)
    risk_signals: Mapped[list] = mapped_column(JSON, default=list)
    missing_data: Mapped[list] = mapped_column(JSON, default=list)

    core_data_quality: Mapped[dict] = mapped_column(JSON, default=dict)
    research_data_coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    live_confirmation_coverage: Mapped[dict] = mapped_column(JSON, default=dict)  # Objective 8: per-source availability

    entry_zone: Mapped[dict] = mapped_column(JSON, default=dict)  # {"low": ..., "high": ...}
    invalidation: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)

    source_provenance: Mapped[dict] = mapped_column(JSON, default=dict)

    # Phase 6 Objective 5 -- diagnostic only, never a trading signal.
    research_minus_mtf: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    research_rank_minus_mtf_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    divergence_classification: Mapped[str] = mapped_column(String(32))  # ResearchDivergenceClass

    # Phase 6 Objective 6 -- forward outcome measurement. All NULL /
    # OUTCOME_PENDING until outcome_engine.py finds real elapsed candles.
    outcome_status: Mapped[str] = mapped_column(String(32), default="OUTCOME_PENDING")
    next_1d_return: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    next_3d_return: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    next_5d_return: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    next_10d_return: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    next_20d_return: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    maximum_favorable_excursion: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    maximum_adverse_excursion: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    invalidation_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    entry_zone_reached: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome_computed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    payload: Mapped[dict] = mapped_column(JSON)  # full ResearchConfirmation.model_dump(), zero information loss

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
