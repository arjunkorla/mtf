"""Walk-forward validation (section 24/30, Phase 6) -- built on top of
app/services/backtest_service.py, not a parallel implementation of it.

This system's scoring weights (app/core/constants.py SCORE_WEIGHTS) are
fixed, not fitted/trained, so there is no parameter-refitting step here --
"walk-forward" in this codebase means walk-forward TESTING: run the exact
same rule-based signal logic across several sequential, non-overlapping
out-of-sample time windows and report each window's stats side by side,
rather than one single backtest over one period (which can't tell you
whether an edge is real or just an artifact of the period chosen).

Deliberately reports the raw per-window numbers (hit rate, avg return,
sample size) rather than computing a single "is this strategy good" verdict
-- consistent with the rest of this project's evidence-over-verdict
philosophy (see e.g. institutional_footprint_engine.py never asserting
"institutions are buying"). A human decides what the spread of numbers
means; this only makes that spread visible.
"""

import datetime as dt
import statistics
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.fyers.fyers_client import FyersClient
from app.logging_config import get_logger
from app.services.backtest_service import (
    DEFAULT_HOLDING_PERIOD_DAYS,
    DEFAULT_MIN_HISTORY_DAYS,
    BacktestSummary,
    SetupStats,
    run_backtest,
    stats_from_trades,
)

logger = get_logger(__name__)

DEFAULT_WINDOW_DAYS = 90


@dataclass
class WalkForwardWindow:
    window_index: int
    start_date: dt.date
    end_date: dt.date
    summary: BacktestSummary


@dataclass
class WalkForwardReport:
    symbol: str
    overall_start: dt.date
    overall_end: dt.date
    window_days: int
    step_days: int
    holding_period_days: int
    windows: list[WalkForwardWindow] = field(default_factory=list)
    combined: SetupStats | None = None
    # Per-window hit_rate_pct for windows that had at least one evaluated
    # setup, in window order -- the actual "does this hold up" evidence.
    hit_rate_by_window: list[float | None] = field(default_factory=list)
    hit_rate_mean: float | None = None
    hit_rate_stdev: float | None = None
    windows_with_no_setups: int = 0


def _generate_windows(start: dt.date, end: dt.date, window_days: int, step_days: int) -> list[tuple[dt.date, dt.date]]:
    if window_days <= 0 or step_days <= 0:
        raise ValueError("window_days and step_days must both be positive")
    if end <= start:
        raise ValueError("end must be after start")

    windows: list[tuple[dt.date, dt.date]] = []
    window_start = start
    while True:
        window_end = window_start + dt.timedelta(days=window_days)
        if window_end > end:
            break
        windows.append((window_start, window_end))
        window_start = window_start + dt.timedelta(days=step_days)

    return windows


async def run_walk_forward_validation(
    client: FyersClient,
    db: AsyncSession,
    symbol: str,
    sector_name: str | None,
    overall_start: dt.date,
    overall_end: dt.date,
    window_days: int = DEFAULT_WINDOW_DAYS,
    step_days: int | None = None,
    holding_period_days: int = DEFAULT_HOLDING_PERIOD_DAYS,
    min_history_days: int = DEFAULT_MIN_HISTORY_DAYS,
    persist_signals: bool = True,
) -> WalkForwardReport:
    """`step_days` defaults to `window_days` (sequential, non-overlapping
    windows -- the standard walk-forward layout). Pass a smaller step for
    overlapping/rolling windows instead.
    """
    step = step_days if step_days is not None else window_days
    date_ranges = _generate_windows(overall_start, overall_end, window_days, step)

    if not date_ranges:
        raise ValueError(
            f"No windows fit in [{overall_start}, {overall_end}] with window_days={window_days}; "
            "shorten window_days or widen the overall range"
        )

    windows: list[WalkForwardWindow] = []
    all_trades = []
    hit_rates: list[float] = []
    windows_with_no_setups = 0

    for i, (w_start, w_end) in enumerate(date_ranges):
        summary = await run_backtest(
            client, db, symbol, sector_name, w_start, w_end,
            holding_period_days=holding_period_days,
            min_history_days=min_history_days,
            persist_signals=persist_signals,
        )
        windows.append(WalkForwardWindow(window_index=i, start_date=w_start, end_date=w_end, summary=summary))
        all_trades.extend(summary.trades)

        if summary.overall and summary.overall.evaluated_count > 0:
            hit_rates.append(summary.overall.hit_rate_pct)
        else:
            windows_with_no_setups += 1

    logger.info(
        "Walk-forward complete: symbol=%s windows=%d range=%s..%s",
        symbol, len(windows), overall_start, overall_end,
    )

    return WalkForwardReport(
        symbol=symbol,
        overall_start=overall_start,
        overall_end=overall_end,
        window_days=window_days,
        step_days=step,
        holding_period_days=holding_period_days,
        windows=windows,
        combined=stats_from_trades(all_trades),
        hit_rate_by_window=[w.summary.overall.hit_rate_pct if w.summary.overall else None for w in windows],
        hit_rate_mean=round(statistics.mean(hit_rates), 2) if hit_rates else None,
        hit_rate_stdev=round(statistics.stdev(hit_rates), 2) if len(hit_rates) >= 2 else None,
        windows_with_no_setups=windows_with_no_setups,
    )
