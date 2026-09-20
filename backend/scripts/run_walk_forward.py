"""Manual entrypoint for walk-forward validation (section 24/30, Phase 6).

Run from backend/:
    python -m scripts.run_walk_forward NSE:RELIANCE-EQ --sector Energy \\
        --start 2025-01-01 --end 2026-06-01 --window-days 90

Splits [start, end) into sequential 90-day (by default) windows and runs
app/services/backtest_service.py's backtest independently on each one, so
you can see whether performance holds up across different periods rather
than trusting one single-period backtest. Same "script, not endpoint"
pattern as scripts/run_backtest.py -- see app/services/walk_forward_service.py
docstring for why.
"""

import argparse
import asyncio
import datetime as dt

from app.db.base import AsyncSessionLocal
from app.integrations.fyers.fyers_client import FyersClient
from app.logging_config import configure_logging, get_logger
from app.services.backtest_service import DEFAULT_HOLDING_PERIOD_DAYS
from app.services.walk_forward_service import DEFAULT_WINDOW_DAYS, run_walk_forward_validation

configure_logging()
logger = get_logger(__name__)


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def _fmt_pct(value: float | None) -> str:
    return f"{value:.2f}%" if value is not None else "N/A"


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run walk-forward validation for one symbol.")
    parser.add_argument("symbol", help='FYERS symbol, e.g. "NSE:RELIANCE-EQ"')
    parser.add_argument("--sector", default=None)
    parser.add_argument("--start", required=True, type=_parse_date, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_parse_date, help="YYYY-MM-DD")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--step-days", type=int, default=None, help="Defaults to --window-days (non-overlapping)")
    parser.add_argument("--holding-period-days", type=int, default=DEFAULT_HOLDING_PERIOD_DAYS)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    client = FyersClient()
    try:
        async with AsyncSessionLocal() as db:
            report = await run_walk_forward_validation(
                client, db, args.symbol, args.sector, args.start, args.end,
                window_days=args.window_days, step_days=args.step_days,
                holding_period_days=args.holding_period_days,
                persist_signals=not args.no_persist,
            )
    finally:
        await client.aclose()

    print(f"\n{report.symbol}  {report.overall_start} -> {report.overall_end}  "
          f"({len(report.windows)} windows of {report.window_days}d, step {report.step_days}d, "
          f"holding {report.holding_period_days}d)")

    print(f"\n{'Window':<8}{'Start':<12}{'End':<12}{'Setups':<8}{'Hit Rate':<12}{'Avg Return':<12}")
    for w in report.windows:
        s = w.summary.overall
        hit_rate = _fmt_pct(s.hit_rate_pct) if s else "N/A"
        avg_return = _fmt_pct(s.avg_forward_return_pct) if s else "N/A"
        setups = s.evaluated_count if s else 0
        print(f"{w.window_index:<8}{str(w.start_date):<12}{str(w.end_date):<12}{setups:<8}{hit_rate:<12}{avg_return:<12}")

    print(f"\nWindows with no actionable setups: {report.windows_with_no_setups}/{len(report.windows)}")
    print(f"Hit rate across windows: mean={_fmt_pct(report.hit_rate_mean)}  stdev={_fmt_pct(report.hit_rate_stdev)}")
    if report.combined:
        c = report.combined
        print(f"\nCombined (all windows pooled): n={c.count} evaluated={c.evaluated_count} "
              f"hit_rate={_fmt_pct(c.hit_rate_pct)} avg_return={_fmt_pct(c.avg_forward_return_pct)}")

    if report.hit_rate_stdev is not None and report.hit_rate_stdev > 25:
        print("\nNote: hit rate varies widely across windows (stdev > 25pp) -- treat the combined")
        print("figure with caution; performance may be concentrated in one period, not consistent.")


if __name__ == "__main__":
    asyncio.run(main())
