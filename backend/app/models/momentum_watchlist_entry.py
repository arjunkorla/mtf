"""Current state of the "MTF INSTITUTIONAL MOMENTUM" dynamic watchlist -- one
row per symbol, re-evaluated on every Momentum Scanner run. `symbol` is
unique so re-qualification after removal reactivates the same row rather
than inserting a duplicate -- see momentum_watchlist_service.py."""

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MomentumWatchlistEntry(Base):
    __tablename__ = "momentum_watchlist_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    status: Mapped[str] = mapped_column(String(16))  # ACTIVE / DOWNGRADED / REMOVED
    qualified_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_scan_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("momentum_scan_runs.id", ondelete="SET NULL"), nullable=True
    )

    current_mtf_status: Mapped[str] = mapped_column(String(32))
    current_effective_leverage: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    current_evidence_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    is_verified_3x_mtf: Mapped[bool] = mapped_column(Boolean, default=False)
    downgrade_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    payload: Mapped[dict] = mapped_column(JSON)  # full MomentumCandidate snapshot as of last evaluation

    history: Mapped[list["MomentumWatchlistHistory"]] = relationship(back_populates="entry")
