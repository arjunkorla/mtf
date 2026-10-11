"""Per-candidate output row for a Momentum Scanner run -- the full
MomentumCandidate payload is persisted as JSON so results can be replayed
without recompute (same pattern as ScannerResult)."""

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MomentumScanResult(Base):
    __tablename__ = "momentum_scan_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("momentum_scan_runs.id", ondelete="CASCADE"), index=True)

    symbol: Mapped[str] = mapped_column(String(32), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    evidence_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    mtf_status: Mapped[str] = mapped_column(String(32))
    is_verified_3x_mtf: Mapped[bool] = mapped_column(Boolean, default=False)

    payload: Mapped[dict] = mapped_column(JSON)  # full MomentumCandidate, frozen at run time

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )

    run: Mapped["MomentumScanRun"] = relationship(back_populates="results")
