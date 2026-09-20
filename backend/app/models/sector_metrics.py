"""Sector/market regime metrics (section 14)."""

import datetime as dt

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SectorMetrics(Base):
    __tablename__ = "sector_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    sector_name: Mapped[str] = mapped_column(String(128), index=True)
    as_of_date: Mapped[dt.date] = mapped_column(nullable=False)

    sector_index_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    relative_strength_vs_nifty: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    momentum_5d_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    momentum_20d_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)

    sector_strength_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    market_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)

    calculated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
