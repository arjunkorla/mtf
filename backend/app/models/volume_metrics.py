"""Volume/accumulation metrics per stock (section 8)."""

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VolumeMetrics(Base):
    __tablename__ = "volume_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"), unique=True, index=True
    )

    as_of_date: Mapped[dt.date] = mapped_column(nullable=False)

    avg_volume_20d: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    relative_volume: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)

    high_volume_up_days_20d: Mapped[int | None] = mapped_column(nullable=True)
    high_volume_down_days_20d: Mapped[int | None] = mapped_column(nullable=True)
    consolidation_volume_avg: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    breakout_volume: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    accumulation_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)

    calculated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
