"""Deterministic per-stock signal snapshot: scoring + setup + footprint.

Stored so historical signals are reproducible for backtesting (section 24)
without look-ahead bias -- each row is pinned to `as_of_date` and computed
only from data available up to that date.
"""

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    as_of_date: Mapped[dt.date] = mapped_column(nullable=False, index=True)

    total_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    score_components: Mapped[dict] = mapped_column(JSON, default=dict)
    unavailable_components: Mapped[list] = mapped_column(JSON, default=list)

    institutional_footprint_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    institutional_footprint_level: Mapped[str] = mapped_column(String(32), default="INSUFFICIENT_DATA")
    institutional_footprint_evidence: Mapped[list] = mapped_column(JSON, default=list)

    setup_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    setup_strength: Mapped[str | None] = mapped_column(String(16), nullable=True)
    supporting_evidence: Mapped[list] = mapped_column(JSON, default=list)
    conflicting_evidence: Mapped[list] = mapped_column(JSON, default=list)
    invalidation_condition: Mapped[str | None] = mapped_column(String(512), nullable=True)

    signal_quality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    data_quality_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
