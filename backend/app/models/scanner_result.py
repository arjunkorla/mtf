"""Per-candidate output row for a scanner run -- the full API response payload
is persisted as JSON so /api/scanner/results can replay it without recompute.
"""

import datetime as dt

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ScannerResult(Base):
    __tablename__ = "scanner_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scanner_runs.id", ondelete="CASCADE"), index=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)

    symbol: Mapped[str] = mapped_column(String(32), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Numeric(6, 2))
    signal_quality: Mapped[str] = mapped_column(String(16))

    payload: Mapped[dict] = mapped_column(JSON)  # full CandidateResponse, frozen at run time

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )

    run: Mapped["ScannerRun"] = relationship(back_populates="results")
