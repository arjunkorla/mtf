"""Market-wide research context, collected once per collection slot and
referenced by every symbol's ResearchObservation taken at that slot (Phase 6
Objective 9) -- avoids storing the same global-macro payload once per stock.
"""

import datetime as dt

from sqlalchemy import JSON, Date, DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchMarketSnapshot(Base):
    __tablename__ = "research_market_snapshots"
    __table_args__ = (
        # One snapshot per configured collection slot per day -- the DB-level
        # guarantee behind "duplicate snapshot prevention" (Phase 6
        # Objective 13), not just an application-level check.
        UniqueConstraint("session_date", "slot_label", name="uq_research_market_snapshot_session_slot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    session_date: Mapped[dt.date] = mapped_column(Date, index=True)
    timestamp_utc: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    timestamp_ist: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))  # derived display value, not authoritative
    slot_label: Mapped[str] = mapped_column(String(16))  # e.g. "10:30" -- the configured slot this snapshot fills

    nifty_regime: Mapped[str] = mapped_column(String(32))  # MarketRegime

    india_vix: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    vix_regime: Mapped[str] = mapped_column(String(32))  # VixRegime

    global_risk_sentiment: Mapped[str] = mapped_column(String(32))  # GlobalRiskSentiment
    global_macro_payload: Mapped[dict] = mapped_column(JSON)  # full GlobalMacroContext.model_dump(), stored ONCE

    source_provenance: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
