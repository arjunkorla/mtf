"""One scheduled MTF evidence-collection stage (Phase D, migration 0005).

stage SCAN:     the unmodified MTF scanner, run after the NSE close on
                COMPLETED daily candles; session_date = that session.
stage GENERATE: the adapter over that SCAN's selected candidates, at a fixed
                slot of the next session with a live generation price;
                session_date = the generation session.

dedup_key = "{stage}|{session_date}|{LIVE|DRY}" (NULL only when an operator
forced a re-run), UNIQUE -- restarts and retries cannot run a stage twice.
"""

import datetime as dt

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MtfCollectionRun(Base):
    __tablename__ = "mtf_collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), index=True)
    session_date: Mapped[dt.date] = mapped_column(Date, index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean)
    forced: Mapped[bool] = mapped_column(Boolean, default=False)
    dedup_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    scanner_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scan_collection_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eligible: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rejected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    persisted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
