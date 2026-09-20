"""Daily OHLCV candles, normalized from FYERS historical data."""

import datetime as dt

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (UniqueConstraint("stock_id", "trade_date", name="uq_price_history_stock_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    trade_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)

    open: Mapped[float] = mapped_column(Numeric(14, 4))
    high: Mapped[float] = mapped_column(Numeric(14, 4))
    low: Mapped[float] = mapped_column(Numeric(14, 4))
    close: Mapped[float] = mapped_column(Numeric(14, 4))
    volume: Mapped[int] = mapped_column()

    source: Mapped[str] = mapped_column(String(32), default="fyers")
    source_timestamp: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC)
    )
