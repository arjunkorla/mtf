"""Response models for the Real-Time Confirmation Engine -- an evidence-
based confirmation layer beside the existing MTF scanner. See
app/services/realtime_confirmation_service.py's module docstring for the
full rationale, and for exactly which fields are and aren't available from
the current live-data feed.
"""

import datetime as dt

from pydantic import BaseModel, Field

from app.schemas.common import EvidenceItem


class PriceConfirmationData(BaseModel):
    status: str  # PriceZoneStatus
    near_invalidation: bool | None = None
    breakout_relation: str  # BreakoutRelation
    observed_price: float | None = None
    entry_zone_low: float
    entry_zone_high: float
    invalidation: float


class VolumeConfirmationData(BaseModel):
    status: str  # VolumeAcceleration
    volume_ratio: float | None = None
    baseline: str = "20-day average daily volume, latest completed session (not real-time intraday volume)"


class VwapConfirmationData(BaseModel):
    status: str  # VwapRelation -- always UNAVAILABLE today, see module docstring
    reason_unavailable: str | None = None


class DepthConfirmationData(BaseModel):
    status: str  # DepthImbalanceLevel
    bid_quantity_total: int | None = None
    ask_quantity_total: int | None = None
    depth_imbalance: float | None = None
    formula: str = "(bid_qty_total - ask_qty_total) / (bid_qty_total + ask_qty_total), summed across the visible 5 levels"
    # Phase 3/5 hardening: cross-checks our summed ladder against FYERS'
    # own totalbuyqty/totalsellqty fields (empirically verified live,
    # 2026-09-20, across 6 real symbols, to be exactly equal -- not a
    # deeper full-book aggregate as an unverified community source
    # claimed). True/False once both are known; None when either side is
    # unavailable to compare.
    ladder_totals_consistent: bool | None = None


class SpreadConditionData(BaseModel):
    status: str  # LiquidityCondition
    spread: float | None = None
    spread_percentage: float | None = None


class FuturesConfirmationData(BaseModel):
    status: str  # FuturesPriceOiState
    futures_price_change_pct: float | None = None
    futures_oi_change_pct: float | None = None
    positioning_proxy: str | None = None  # the existing, already-labeled scanner proxy -- informational only


class PersistenceData(BaseModel):
    status: str  # PersistenceState
    observation_count: int
    window: int
    first_observed_status: str | None = None
    latest_status: str | None = None


class RealtimeConfirmationResponse(BaseModel):
    symbol: str
    timestamp: dt.datetime
    freshness: str  # LIVE | STALE | UNAVAILABLE, of the underlying live quote (unchanged 3-value contract)
    market_status: str  # MARKET_OPEN_LIVE | MARKET_CLOSED_LAST_AVAILABLE | STALE | UNAVAILABLE (additive, Phase 6 hardening)
    confirmation_status: str  # ConfirmationStatus -- describes current evidence, not a prediction
    confirmation_score: float | None = None  # experimental, see CONFIRMATION_WEIGHTS
    data_quality: str  # ConfirmationDataQuality

    price_confirmation: PriceConfirmationData
    volume_confirmation: VolumeConfirmationData
    vwap_confirmation: VwapConfirmationData
    depth_confirmation: DepthConfirmationData
    spread_condition: SpreadConditionData
    futures_confirmation: FuturesConfirmationData
    persistence: PersistenceData

    evidence: list[EvidenceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
