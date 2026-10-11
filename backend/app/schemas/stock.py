"""Response models for stock detail / analysis endpoints and the building
blocks reused by the scanner candidate response (section 6-14, 20).
"""

import datetime as dt

from pydantic import BaseModel, Field

from app.schemas.common import EvidenceItem


class MarketData(BaseModel):
    price: float
    change_pct: float | None = None
    volume: int | None = None
    avg_volume_20d: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    as_of: dt.datetime
    # Phase D (additive): what `as_of` actually means, and the FYERS quote's
    # session-date stamp (its `tt` field) -- never an exchange trade time.
    as_of_basis: str | None = None
    quote_session_date: dt.date | None = None


class TechnicalData(BaseModel):
    ema_20: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None
    rsi_14: float | None = None
    atr_14: float | None = None
    adx_14: float | None = None
    vwap: float | None = None
    recent_high_20d: float | None = None
    recent_low_20d: float | None = None
    support_level: float | None = None
    resistance_level: float | None = None
    trend_structure: str | None = None
    breakout_status: str | None = None
    pullback_status: str | None = None


class VolumeData(BaseModel):
    volume_ratio: float | None = None
    relative_volume: float | None = None
    high_volume_up_days_20d: int | None = None
    high_volume_down_days_20d: int | None = None
    breakout_volume: float | None = None
    accumulation_score: float | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)


class FnoData(BaseModel):
    is_available: bool
    futures_price_change_pct: float | None = None
    futures_oi_change_pct: float | None = None
    put_call_oi_ratio: float | None = None
    positioning_proxy: str = "NOT_AVAILABLE"
    evidence: list[EvidenceItem] = Field(default_factory=list)


class FundamentalData(BaseModel):
    is_available: bool
    revenue_growth_yoy_pct: float | None = None
    profit_growth_yoy_pct: float | None = None
    eps: float | None = None
    net_margin_pct: float | None = None
    debt_to_equity: float | None = None
    roe_pct: float | None = None
    roce_pct: float | None = None
    pe_ratio: float | None = None


class NewsCatalystItem(BaseModel):
    headline: str
    category: str | None = None
    sentiment: str = "UNKNOWN"
    source: str
    source_url: str | None = None
    published_at: dt.datetime


class NewsData(BaseModel):
    items: list[NewsCatalystItem] = Field(default_factory=list)
    overall_sentiment: str = "UNKNOWN"


class RelativeStrengthData(BaseModel):
    label: str  # OUTPERFORM/UNDERPERFORM/NEUTRAL/INSUFFICIENT_DATA
    vs_nifty_pct_20d: float | None = None
    vs_sector_pct_20d: float | None = None


class SectorData(BaseModel):
    sector_name: str | None = None
    sector_strength_label: str | None = None
    market_regime: str | None = None
    relative_strength: RelativeStrengthData


class StockSummary(BaseModel):
    symbol: str
    company_name: str
    sector: str | None = None
    is_fno: bool
    is_mtf_eligible: bool
