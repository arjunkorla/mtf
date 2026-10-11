"""Append-only transition log for the momentum watchlist. Kept as a separate
table (not a JSON array on the entry row) so "alert only on real change"
(telegram_alert_service.py) is a simple query against the latest row, not a
diff against a JSON blob."""

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, JSON, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MomentumWatchlistHistory(Base):
    __tablename__ = "momentum_watchlist_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("momentum_watchlist_entries.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)

    # QUALIFIED / RE_EVALUATED / IMPROVED / DETERIORATED / DOWNGRADED / REMOVED
    event_type: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(512))

    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_status: Mapped[str] = mapped_column(String(16))
    previous_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    new_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )

    entry: Mapped["MomentumWatchlistEntry"] = relationship(back_populates="history")
