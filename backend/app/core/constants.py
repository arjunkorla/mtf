"""Shared enums and constants used across engines and schemas."""

from enum import StrEnum


class InstitutionalFootprintLevel(StrEnum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RelativeStrengthLabel(StrEnum):
    OUTPERFORM = "OUTPERFORM"
    UNDERPERFORM = "UNDERPERFORM"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class FnoPositioningProxy(StrEnum):
    LONG_BUILDUP = "LONG_BUILDUP_PROXY"
    SHORT_BUILDUP = "SHORT_BUILDUP_PROXY"
    SHORT_COVERING = "SHORT_COVERING_PROXY"
    LONG_UNWINDING = "LONG_UNWINDING_PROXY"
    NEUTRAL = "NEUTRAL"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class NewsSentiment(StrEnum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"
    UNKNOWN = "UNKNOWN"


class MarketRegime(StrEnum):
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SetupType(StrEnum):
    TREND_CONTINUATION = "TREND_CONTINUATION"
    BREAKOUT = "BREAKOUT"
    BREAKOUT_RETEST = "BREAKOUT_RETEST"
    PULLBACK = "PULLBACK"
    ACCUMULATION_BREAKOUT = "ACCUMULATION_BREAKOUT"
    RELATIVE_STRENGTH_CONTINUATION = "RELATIVE_STRENGTH_CONTINUATION"
    NONE = "NONE"


class SignalQuality(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PriceZoneStatus(StrEnum):
    ABOVE_ENTRY_ZONE = "ABOVE_ENTRY_ZONE"
    INSIDE_ENTRY_ZONE = "INSIDE_ENTRY_ZONE"
    BELOW_ENTRY_ZONE = "BELOW_ENTRY_ZONE"
    UNAVAILABLE = "UNAVAILABLE"


class BreakoutRelation(StrEnum):
    ABOVE_BREAKOUT_LEVEL = "ABOVE_BREAKOUT_LEVEL"
    BELOW_BREAKOUT_LEVEL = "BELOW_BREAKOUT_LEVEL"
    NO_BREAKOUT_LEVEL = "NO_BREAKOUT_LEVEL"
    UNAVAILABLE = "UNAVAILABLE"


class VolumeAcceleration(StrEnum):
    EXPANDING = "EXPANDING"
    NORMAL = "NORMAL"
    DECLINING = "DECLINING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VwapRelation(StrEnum):
    ABOVE_VWAP = "ABOVE_VWAP"
    NEAR_VWAP = "NEAR_VWAP"
    BELOW_VWAP = "BELOW_VWAP"
    UNAVAILABLE = "UNAVAILABLE"


class DepthImbalanceLevel(StrEnum):
    STRONG_BID = "STRONG_BID"
    MODERATE_BID = "MODERATE_BID"
    BALANCED = "BALANCED"
    MODERATE_ASK = "MODERATE_ASK"
    STRONG_ASK = "STRONG_ASK"
    UNAVAILABLE = "UNAVAILABLE"


class LiquidityCondition(StrEnum):
    HEALTHY = "HEALTHY"
    WIDE = "WIDE"
    UNAVAILABLE = "UNAVAILABLE"


class FuturesPriceOiState(StrEnum):
    PRICE_UP_OI_UP = "PRICE_UP_OI_UP"
    PRICE_UP_OI_DOWN = "PRICE_UP_OI_DOWN"
    PRICE_DOWN_OI_UP = "PRICE_DOWN_OI_UP"
    PRICE_DOWN_OI_DOWN = "PRICE_DOWN_OI_DOWN"
    FLAT = "FLAT"
    UNAVAILABLE = "UNAVAILABLE"


class PersistenceState(StrEnum):
    INSUFFICIENT_OBSERVATIONS = "INSUFFICIENT_OBSERVATIONS"
    STRENGTHENING = "STRENGTHENING"
    PERSISTED = "PERSISTED"
    WEAKENING = "WEAKENING"
    DISAPPEARED = "DISAPPEARED"


class ConfirmationDataQuality(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ConfirmationStatus(StrEnum):
    STRONGLY_SUPPORTIVE = "STRONGLY_SUPPORTIVE"
    SUPPORTIVE = "SUPPORTIVE"
    NEUTRAL = "NEUTRAL"
    CONTRADICTORY = "CONTRADICTORY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Real-Time Confirmation Engine weights (section: realtime confirmation,
# 2026-09-20). EXPERIMENTAL -- unlike SCORE_WEIGHTS above (the real,
# production MTF score), these are explicitly NOT approved production
# weights. They exist so the confirmation score has one documented,
# editable source instead of magic numbers scattered through the service,
# not because these specific values have been validated. Re-normalized
# against whichever components are actually available for a given symbol
# (same pattern as scoring_engine.compute_score) -- e.g. VWAP is currently
# always UNAVAILABLE (the live feed runs in litemode, no intraday VWAP
# source exists yet -- see realtime_confirmation_service.py's module
# docstring), so its 15% is redistributed across the other components,
# never silently dropped or treated as zero.
CONFIRMATION_WEIGHTS = {
    "price": 25,
    "volume": 20,
    "vwap": 15,
    "depth": 15,
    "futures": 15,
    "persistence": 10,
}

assert sum(CONFIRMATION_WEIGHTS.values()) == 100


# Scoring engine component weights (must sum to 100)
SCORE_WEIGHTS = {
    "technical_structure": 20,
    "volume_accumulation": 20,
    "relative_strength": 15,
    "fno_positioning": 15,
    "fundamentals": 10,
    "catalyst_news": 10,
    "market_sector": 5,
    "data_quality": 5,
}

assert sum(SCORE_WEIGHTS.values()) == 100

# --- Research confirmation layer (Phase 5, 2026-09-21) ---
# EXPERIMENTAL, separate from the production MTF score above. Never
# imported by scoring_engine.py/scanner_service.py.


class ResearchStatus(StrEnum):
    HIGH_CONFIRMATION = "HIGH_CONFIRMATION"
    SUPPORTIVE = "SUPPORTIVE"
    NEUTRAL = "NEUTRAL"
    CONFLICTING = "CONFLICTING"
    WEAK = "WEAK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VixRegime(StrEnum):
    LOW_VOLATILITY = "LOW_VOLATILITY"
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    # RISING/FALLING deliberately not modeled: this system has no persisted
    # VIX history, so a trend call from a single live snapshot would be a
    # fabricated trend, not measured evidence -- see india_vix_engine.py.


class MacroSessionState(StrEnum):
    LIVE_SESSION = "LIVE_SESSION"
    LAST_AVAILABLE_SNAPSHOT = "LAST_AVAILABLE_SNAPSHOT"
    UNAVAILABLE = "UNAVAILABLE"


class GlobalRiskSentiment(StrEnum):
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    MIXED = "MIXED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Research-layer component weights (must sum to 100). EXPERIMENTAL --
# unlike SCORE_WEIGHTS above, these are not production-approved and have
# not been backtested; see research_confirmation_engine.py's module
# docstring for the double-counting analysis behind each weight, especially
# why institutional_footprint (15, not ~25+) and live_confirmation (10, not
# ~20+) are deliberately smaller than a "naive equal split" would give them.
RESEARCH_WEIGHTS = {
    "technical_and_relative_strength": 20,
    "institutional_footprint": 15,
    "futures_options_positioning": 12,
    "live_confirmation": 10,
    "market_regime_and_global_sentiment": 12,
    "sector_context": 10,
    "catalyst_news": 8,
    "corporate_events": 8,  # always unavailable today -- see CorporateEventContext
    "data_quality": 5,
}

assert sum(RESEARCH_WEIGHTS.values()) == 100


# --- MTF leverage verification (Momentum Scanner automation) ---
# Never assume leverage: UNVERIFIED is the default whenever FYERS margin
# data cannot be confirmed for a symbol, not a fallback path that gets
# skipped in the happy case. See mtf_leverage_engine.py.


class MtfLeverageStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    NOT_MTF_ELIGIBLE = "NOT_MTF_ELIGIBLE"


MIN_VERIFIED_LEVERAGE = 3.0


# --- Momentum Scanner automation ranking layer ---
# EXPERIMENTAL, separate from the production MTF score (SCORE_WEIGHTS above)
# and from the Research Confirmation layer (RESEARCH_WEIGHTS above). Never
# imported by scoring_engine.py/scanner_service.py. See
# momentum_ranking_engine.py. bulk_block_deal_evidence's 15% is always
# unavailable today (no bulk/block-deal data source exists) and is excluded
# from every candidate's re-normalization denominator -- it never silently
# becomes a zero and is never awarded points either.
MOMENTUM_SCAN_WEIGHTS = {
    "institutional_footprint": 25,
    "bulk_block_deal_evidence": 15,
    "volume_and_delivery": 20,
    "technical_momentum": 15,
    "breakout_structure": 10,
    "relative_strength": 5,
    "liquidity": 5,
    "mtf_characteristics": 5,
}

assert sum(MOMENTUM_SCAN_WEIGHTS.values()) == 100

MOMENTUM_LABEL = "EXPERIMENTAL -- separate from the production MTF score, not backtested"


# Candidate filtering defaults (overridable via /api/settings)
DEFAULT_MIN_PRICE = 20.0
DEFAULT_MIN_AVG_DAILY_TURNOVER = 5_00_00_000  # INR 5 crore
DEFAULT_MIN_AVG_DAILY_VOLUME = 100_000
DEFAULT_MIN_HISTORY_DAYS = 100
DEFAULT_MAX_CANDIDATES = 10
DEFAULT_MIN_CANDIDATES = 3
