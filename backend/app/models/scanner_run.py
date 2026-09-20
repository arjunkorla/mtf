"""One row per POST /api/scanner/run invocation."""

import datetime as dt

from sqlalchemy import JSON, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ScannerRun(Base):
    __tablename__ = "scanner_runs"

    id: Mapped[int] = mapped_column(primary_key=True)

    available_capital: Mapped[float] = mapped_column(Numeric(18, 2))
    risk_percent: Mapped[float] = mapped_column(Numeric(6, 3))
    max_positions: Mapped[int] = mapped_column(Integer)
    holding_period: Mapped[str] = mapped_column(String(32))

    status: Mapped[str] = mapped_column(String(16), default="running")  # running/completed/failed
    stocks_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    stocks_rejected: Mapped[int] = mapped_column(Integer, default=0)
    stocks_selected: Mapped[int] = mapped_column(Integer, default=0)
    execution_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    rejection_summary: Mapped[dict] = mapped_column(JSON, default=dict)

    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    results: Mapped[list["ScannerResult"]] = relationship(back_populates="run")
