"""Backtest orchestration (section 24) -- Phase 6.

Walks a symbol's real daily history day-by-day, computing a signal from only
the data available as of each date (app/engines/backtest_engine.py), then
looks forward to see what actually happened. Persists each day's signal to
the existing `signals` table (its docstring already describes exactly this
use case) and returns an aggregated hit-rate/return summary.

Deliberately NOT exposed as a REST endpoint (section 24: "Do NOT build a
complex backtesting UI initially") -- run via scripts/run_backtest.py, same
pattern as scripts/sync_universe.py.

Fundamentals, news, and F&O are excluded from backtest scoring -- see
app/engines/backtest_engine.py for why (no point-in-time history for them
in this system, so using "current" values would itself be look-ahead bias).
"""

import bisect
import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.internal_models import Candle
from app.data.normalization import normalize_history
from app.data.sector_index_map import get_sector_index_symbol
from app.data.universe import NIFTY_INDEX_SYMBOL
from app.engines.backtest_engine import ForwardOutcome, HistoricalSignal, compute_historical_signal, evaluate_forward_outcome
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.historical_data import get_daily_history
from app.logging_config import get_logger
from app.models.signal import Signal
from app.models.stock import Stock

logger = get_logger(__name__)

DEFAULT_MIN_HISTORY_DAYS = 100
DEFAULT_HOLDING_PERIOD_DAYS = 20  # ~ 4 trading weeks, matching the product's "1-4 weeks" horizon


@dataclass
class BacktestTrade:
    as_of_date: dt.date
    setup_type: str
    setup_strength: str | None
    signal_quality: str
    score: float
    entry_price: float
    invalidation_price: float
    resistance_1: float
    resistance_2: float | None
    outcome: str
    forward_return_pct: float | None
    trading_days_to_outcome: int | None


@dataclass
class SetupStats:
    count: int
    evaluated_count: int  # excludes INSUFFICIENT_FORWARD_DATA
    hit_rate_pct: float | None  # (TARGET_1_HIT or TARGET_2_HIT) / evaluated_count
    avg_forward_return_pct: float | None
    avg_trading_days_to_outcome: float | None


@dataclass
class BacktestSummary:
    symbol: str
    start_date: dt.date
    end_date: dt.date
    holding_period_days: int
    signals_generated: int
    trades: list[BacktestTrade] = field(default_factory=list)
    by_setup_type: dict[str, SetupStats] = field(default_factory=dict)
    overall: SetupStats | None = None


async def _fetch_range_history(client: FyersClient, symbol: str, range_from: dt.date, range_to: dt.date) -> list[Candle]:
    raw = await get_daily_history(client, symbol, range_from, range_to)
    return normalize_history(raw)


def _truncate(candles: list[Candle], dates: list[dt.date], as_of: dt.date) -> list[Candle]:
    """Candles up to and including `as_of`, using the parallel sorted `dates`
    list for an O(log n) cut instead of a fresh filter per day."""
    idx = bisect.bisect_right(dates, as_of)
    return candles[:idx]


def stats_from_trades(trades: list[BacktestTrade]) -> SetupStats:
    evaluated = [t for t in trades if t.outcome != "INSUFFICIENT_FORWARD_DATA"]
    hits = [t for t in evaluated if t.outcome in ("TARGET_1_HIT", "TARGET_2_HIT")]
    returns = [t.forward_return_pct for t in evaluated if t.forward_return_pct is not None]
    days = [t.trading_days_to_outcome for t in evaluated if t.trading_days_to_outcome is not None]

    return SetupStats(
        count=len(trades),
        evaluated_count=len(evaluated),
        hit_rate_pct=round(len(hits) / len(evaluated) * 100, 2) if evaluated else None,
        avg_forward_return_pct=round(sum(returns) / len(returns), 3) if returns else None,
        avg_trading_days_to_outcome=round(sum(days) / len(days), 2) if days else None,
    )


async def _upsert_signal(db: AsyncSession, stock_id: int, as_of_date: dt.date, signal: HistoricalSignal) -> None:
    existing = (
        await db.execute(select(Signal).where(Signal.stock_id == stock_id, Signal.as_of_date == as_of_date))
    ).scalar_one_or_none()

    if existing is None:
        existing = Signal(stock_id=stock_id, as_of_date=as_of_date)
        db.add(existing)

    existing.total_score = signal.total_score
    existing.score_components = signal.score_components
    existing.unavailable_components = signal.unavailable_components
    existing.institutional_footprint_score = signal.institutional_footprint_score
    existing.institutional_footprint_level = signal.institutional_footprint_level
    existing.institutional_footprint_evidence = signal.institutional_footprint_evidence
    existing.setup_type = signal.setup_type
    existing.setup_strength = signal.setup_strength
    existing.supporting_evidence = signal.supporting_evidence
    existing.conflicting_evidence = signal.conflicting_evidence
    existing.invalidation_condition = signal.invalidation_condition
    existing.signal_quality = signal.signal_quality
    existing.data_quality_score = signal.data_quality_score


async def run_backtest(
    client: FyersClient,
    db: AsyncSession,
    symbol: str,
    sector_name: str | None,
    start_date: dt.date,
    end_date: dt.date,
    holding_period_days: int = DEFAULT_HOLDING_PERIOD_DAYS,
    min_history_days: int = DEFAULT_MIN_HISTORY_DAYS,
    persist_signals: bool = True,
) -> BacktestSummary:
    if end_date <= start_date:
        raise ValueError("end_date must be after start_date")

    # Buffers: extra lookback for indicator warmup before start_date, extra
    # lookahead past end_date so the last few signals still have a full
    # holding period to evaluate against. 1.5x accounts for weekends/holidays
    # converting calendar days to trading days.
    fetch_from = start_date - dt.timedelta(days=int(min_history_days * 1.5) + 10)
    fetch_to = end_date + dt.timedelta(days=int(holding_period_days * 1.5) + 10)
    fetch_to = min(fetch_to, dt.date.today())

    candles = await _fetch_range_history(client, symbol, fetch_from, fetch_to)
    nifty_candles = await _fetch_range_history(client, NIFTY_INDEX_SYMBOL, fetch_from, fetch_to)

    sector_index_symbol = get_sector_index_symbol(sector_name)
    sector_candles = await _fetch_range_history(client, sector_index_symbol, fetch_from, fetch_to) if sector_index_symbol else None

    dates = [c.trade_date for c in candles]
    nifty_dates = [c.trade_date for c in nifty_candles]
    sector_dates = [c.trade_date for c in sector_candles] if sector_candles else []

    stock_row = None
    if persist_signals:
        stock_row = (await db.execute(select(Stock).where(Stock.symbol == symbol))).scalar_one_or_none()
        if stock_row is None:
            logger.warning("Backtest for %s: not found in stocks table, signals will not be persisted", symbol)

    trades: list[BacktestTrade] = []
    signals_generated = 0

    for idx, candle in enumerate(candles):
        d = candle.trade_date
        if d < start_date or d > end_date:
            continue

        candles_upto_d = candles[: idx + 1]
        if len(candles_upto_d) < min_history_days:
            continue

        nifty_upto_d = _truncate(nifty_candles, nifty_dates, d)
        sector_upto_d = _truncate(sector_candles, sector_dates, d) if sector_candles else None

        signal = compute_historical_signal(candles_upto_d, nifty_upto_d, sector_upto_d, sector_name)
        signals_generated += 1

        if stock_row is not None:
            await _upsert_signal(db, stock_row.id, d, signal)

        if signal.setup_type == "NONE":
            continue

        future_candles = candles[idx + 1 :]
        outcome: ForwardOutcome = evaluate_forward_outcome(
            future_candles,
            entry_price=signal.scenarios.preferred_entry,
            invalidation_price=signal.scenarios.invalidation,
            resistance_1=signal.scenarios.resistance_scenario_1,
            resistance_2=signal.scenarios.resistance_scenario_2,
            holding_period_days=holding_period_days,
        )

        trades.append(
            BacktestTrade(
                as_of_date=d,
                setup_type=signal.setup_type,
                setup_strength=signal.setup_strength,
                signal_quality=signal.signal_quality,
                score=signal.total_score,
                entry_price=signal.scenarios.preferred_entry,
                invalidation_price=signal.scenarios.invalidation,
                resistance_1=signal.scenarios.resistance_scenario_1,
                resistance_2=signal.scenarios.resistance_scenario_2,
                outcome=outcome.label,
                forward_return_pct=outcome.forward_return_pct,
                trading_days_to_outcome=outcome.trading_days_to_outcome,
            )
        )

    if persist_signals and stock_row is not None:
        await db.commit()

    by_setup_type: dict[str, SetupStats] = {}
    for setup_type in {t.setup_type for t in trades}:
        by_setup_type[setup_type] = stats_from_trades([t for t in trades if t.setup_type == setup_type])

    logger.info(
        "Backtest complete: symbol=%s signals=%d trades=%d range=%s..%s",
        symbol, signals_generated, len(trades), start_date, end_date,
    )

    return BacktestSummary(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        holding_period_days=holding_period_days,
        signals_generated=signals_generated,
        trades=trades,
        by_setup_type=by_setup_type,
        overall=stats_from_trades(trades),
    )
