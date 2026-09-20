"""Backtesting engine (section 24) -- Phase 6.

Pure, IO-free functions only: given a candle slice, compute the same kind of
signal the live pipeline produces; given a forward candle slice, evaluate
what happened after. app/services/backtest_service.py owns fetching data,
walking dates, and persistence -- this module never reads the clock, the
network, or the database, which is what makes it trustworthy for
look-ahead-bias-free simulation in the first place.

Fundamentals, news, and F&O are deliberately excluded from the historical
score (see backtest_service.py docstring): this system has no point-in-time
history for them, so including "current" values would itself be a form of
look-ahead bias. The scoring engine already re-normalizes over whatever
components ARE available, so no special-casing is needed here -- we simply
never feed it those three.
"""

from dataclasses import dataclass

from app.data.internal_models import Candle
from app.engines import (
    institutional_footprint_engine,
    market_sector_engine,
    relative_strength_engine,
    scenario_engine,
    scoring_engine,
    setup_detection_engine,
    technical_engine,
    volume_engine,
)
from app.engines.data_quality_engine import compute_data_quality
from app.schemas.common import ScenarioLevels
from app.schemas.stock import FnoData, FundamentalData, NewsData

# Fixed "not available in backtest mode" placeholders -- never fabricated
# values, just the same explicit-unavailable shapes the live pipeline uses
# when a real source is missing.
_NO_FNO = FnoData(is_available=False, positioning_proxy="NOT_AVAILABLE")
_NO_FUNDAMENTALS = FundamentalData(is_available=False)
_NO_NEWS = NewsData(items=[], overall_sentiment="UNKNOWN")


@dataclass
class HistoricalSignal:
    as_of_date_index: int  # index into the caller's candle list, for traceability
    total_score: float
    score_components: list[dict]
    unavailable_components: list[str]
    institutional_footprint_score: float | None
    institutional_footprint_level: str
    institutional_footprint_evidence: list[dict]
    setup_type: str
    setup_strength: str | None
    supporting_evidence: list[dict]
    conflicting_evidence: list[dict]
    invalidation_condition: str | None
    signal_quality: str
    data_quality_score: float
    scenarios: ScenarioLevels


def compute_historical_signal(
    candles_upto_date: list[Candle],
    nifty_candles_upto_date: list[Candle],
    sector_candles_upto_date: list[Candle] | None,
    sector_name: str | None,
) -> HistoricalSignal:
    """`candles_upto_date` etc. must already be truncated by the caller to
    `trade_date <= D` -- this function trusts that truncation completely and
    does no date filtering of its own.
    """
    last_close = candles_upto_date[-1].close

    technical = technical_engine.compute_technical_metrics(candles_upto_date)
    volume = volume_engine.compute_volume_metrics(candles_upto_date)

    relative_strength = relative_strength_engine.compute_relative_strength(
        candles_upto_date, nifty_candles_upto_date, sector_candles_upto_date
    )
    sector_data = market_sector_engine.build_sector_data(
        sector_name, sector_candles_upto_date, nifty_candles_upto_date, relative_strength
    )

    footprint = institutional_footprint_engine.compute_institutional_footprint(volume, relative_strength, _NO_FNO)
    setup = setup_detection_engine.detect_setup(technical, volume, relative_strength)

    available_sources = {"price_history", "volume_metrics"}
    if sector_data.sector_strength_label is not None:
        available_sources.add("sector_metrics")
    # No source_timestamps: backtest signals have no "fetched at" concept, and
    # compute_data_quality only checks staleness when a timestamp is present,
    # so an empty dict correctly never triggers a staleness penalty here.
    data_quality = compute_data_quality(source_timestamps={}, available_sources=available_sources)

    total_score, components, signal_quality = scoring_engine.compute_score(
        technical, volume, relative_strength, _NO_FNO, _NO_FUNDAMENTALS, _NO_NEWS,
        sector_data, data_quality.data_quality_score,
    )

    scenarios = scenario_engine.build_scenarios(last_close, technical)

    return HistoricalSignal(
        as_of_date_index=len(candles_upto_date) - 1,
        total_score=total_score,
        score_components=[c.model_dump() for c in components],
        unavailable_components=[c.name for c in components if not c.available],
        institutional_footprint_score=footprint.institutional_footprint_score,
        institutional_footprint_level=footprint.institutional_footprint_level,
        institutional_footprint_evidence=[e.model_dump() for e in footprint.evidence],
        setup_type=setup.setup_type,
        setup_strength=setup.setup_strength,
        supporting_evidence=[e.model_dump() for e in setup.supporting_evidence],
        conflicting_evidence=[e.model_dump() for e in setup.conflicting_evidence],
        invalidation_condition=setup.invalidation_condition,
        signal_quality=signal_quality,
        data_quality_score=data_quality.data_quality_score,
        scenarios=scenarios,
    )


@dataclass
class ForwardOutcome:
    label: str  # TARGET_1_HIT | TARGET_2_HIT | INVALIDATED | TIME_EXIT | INSUFFICIENT_FORWARD_DATA
    forward_return_pct: float | None
    trading_days_to_outcome: int | None


def evaluate_forward_outcome(
    future_candles: list[Candle],
    entry_price: float,
    invalidation_price: float,
    resistance_1: float,
    resistance_2: float | None,
    holding_period_days: int,
) -> ForwardOutcome:
    """`future_candles` must be strictly AFTER the signal date, chronological
    order, not truncated to the holding period -- this function stops on its
    own once it has walked `holding_period_days` bars or run out of data.

    Daily OHLC bars can't tell us whether invalidation or a resistance level
    was touched first intraday if both happened the same session -- this
    checks invalidation first on any day it and a resistance level are both
    touched, the conservative (risk-first) assumption, documented rather
    than left as a silent simplification.
    """
    window = future_candles[:holding_period_days]
    if not window:
        return ForwardOutcome(label="INSUFFICIENT_FORWARD_DATA", forward_return_pct=None, trading_days_to_outcome=None)

    for i, candle in enumerate(window, start=1):
        if candle.low <= invalidation_price:
            ret = (invalidation_price - entry_price) / entry_price * 100
            return ForwardOutcome(label="INVALIDATED", forward_return_pct=round(ret, 3), trading_days_to_outcome=i)
        if resistance_2 is not None and candle.high >= resistance_2:
            ret = (resistance_2 - entry_price) / entry_price * 100
            return ForwardOutcome(label="TARGET_2_HIT", forward_return_pct=round(ret, 3), trading_days_to_outcome=i)
        if candle.high >= resistance_1:
            ret = (resistance_1 - entry_price) / entry_price * 100
            return ForwardOutcome(label="TARGET_1_HIT", forward_return_pct=round(ret, 3), trading_days_to_outcome=i)

    if len(future_candles) < holding_period_days:
        # Ran out of history before the holding period elapsed -- exiting at
        # the last available close would silently understate/overstate the
        # true time-exit return, so this is reported as insufficient rather
        # than guessed.
        return ForwardOutcome(label="INSUFFICIENT_FORWARD_DATA", forward_return_pct=None, trading_days_to_outcome=None)

    exit_close = window[-1].close
    ret = (exit_close - entry_price) / entry_price * 100
    return ForwardOutcome(label="TIME_EXIT", forward_return_pct=round(ret, 3), trading_days_to_outcome=holding_period_days)
