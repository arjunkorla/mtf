"""F&O price/OI proxy metrics per stock (section 11). Populated only for F&O stocks."""

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FnoMetrics(Base):
    __tablename__ = "fno_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"), unique=True, index=True
    )

    as_of_date: Mapped[dt.date] = mapped_column(nullable=False)

    futures_price_change_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    futures_oi_change_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    futures_volume: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)

    call_oi_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    put_oi_total: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    put_call_oi_ratio: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    max_oi_strike_call: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    max_oi_strike_put: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)

    positioning_proxy: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_available: Mapped[bool] = mapped_column(default=False)

    calculated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
