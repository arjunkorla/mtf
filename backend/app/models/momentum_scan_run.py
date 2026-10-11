"""One row per Momentum Scanner automation run (scheduled or manual-script).

Uniqueness on (session_date, slot_label) is the idempotency guard: if the
scheduler fires twice for the same slot (dev --reload, a misfire after
downtime), the second attempt is a safe no-op -- see momentum_scan_service.py.
"""

import datetime as dt

from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MomentumScanRun(Base):
    __tablename__ = "momentum_scan_runs"
    __table_args__ = (UniqueConstraint("session_date", "slot_label", name="uq_momentum_scan_run_session_slot"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    session_date: Mapped[dt.date] = mapped_column(index=True)
    slot_label: Mapped[str] = mapped_column(String(16))

    status: Mapped[str] = mapped_column(String(32), default="running")  # running/completed/failed
    stocks_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    verified_3x_mtf_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    rejection_summary: Mapped[dict] = mapped_column(JSON, default=dict)

    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    results: Mapped[list["MomentumScanResult"]] = relationship(back_populates="run")
