"""Latest computed technical indicators per stock (section 7)."""

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TechnicalMetrics(Base):
    __tablename__ = "technical_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"), unique=True, index=True
    )

    as_of_date: Mapped[dt.date] = mapped_column(nullable=False)

    ema_20: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    ema_50: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    ema_200: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    rsi_14: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    atr_14: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    adx_14: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    vwap: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)

    recent_high_20d: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    recent_low_20d: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    support_level: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    resistance_level: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)

    trend_structure: Mapped[str | None] = mapped_column(String(32), nullable=True)
    breakout_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    pullback_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    calculated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
