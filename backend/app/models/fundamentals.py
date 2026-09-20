"""Validated fundamental data per stock (section 12)."""

import datetime as dt

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Fundamentals(Base):
    __tablename__ = "fundamentals"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(
        ForeignKey("stocks.id", ondelete="CASCADE"), unique=True, index=True
    )

    revenue_growth_yoy_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    profit_growth_yoy_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    eps: Mapped[float | None] = mapped_column(Numeric(14, 4), nullable=True)
    net_margin_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    roe_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    roce_pct: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    pe_ratio: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    pb_ratio: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)

    is_available: Mapped[bool] = mapped_column(default=False)
    fiscal_period: Mapped[str | None] = mapped_column(nullable=True)

    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
