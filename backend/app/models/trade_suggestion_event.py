"""Append-only lifecycle log for TradeSuggestion (Phase A).

Rows are never updated or deleted: guarded at the ORM level here, and at the
database level by a PostgreSQL trigger created in migration 0003.

For threshold events (entry/target/stop/invalidation) the threshold level
and the price actually observed in the market are stored separately, with
`observed_price_basis` saying how that observation was made -- so a gap
through a stop/target is never recorded as an exact fill at the level.
"""

import datetime as dt

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TradeSuggestionEvent(Base):
    __tablename__ = "trade_suggestion_events"
    __table_args__ = (UniqueConstraint("suggestion_id", "sequence", name="uq_trade_suggestion_event_sequence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    suggestion_id: Mapped[int] = mapped_column(
        ForeignKey("trade_suggestions.id", ondelete="RESTRICT"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)  # 1, 2, 3... per suggestion

    event_type: Mapped[str] = mapped_column(String(48), index=True)  # SuggestionEventType
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    threshold_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    observed_market_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    observed_price_basis: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ambiguous_bar: Mapped[bool] = mapped_column(Boolean, default=False)

    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    recorded_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))

    suggestion: Mapped["TradeSuggestion"] = relationship(back_populates="events")  # noqa: F821


class AppendOnlyViolation(RuntimeError):
    pass


@event.listens_for(TradeSuggestionEvent, "before_update")
def _refuse_update(mapper, connection, target) -> None:
    raise AppendOnlyViolation("trade_suggestion_events is append-only: updates are not allowed")


@event.listens_for(TradeSuggestionEvent, "before_delete")
def _refuse_delete(mapper, connection, target) -> None:
    raise AppendOnlyViolation("trade_suggestion_events is append-only: deletes are not allowed")
