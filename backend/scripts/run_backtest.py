"""Manual entrypoint for running a backtest (section 24, Phase 6).

Run from backend/:
    python -m scripts.run_backtest NSE:RELIANCE-EQ --sector Energy --start 2025-01-01 --end 2026-06-01

Deliberately a script, not a REST endpoint -- section 24 says not to build a
complex backtesting UI initially, and app/services/backtest_service.py's
docstring explains why (same reasoning as scripts/sync_universe.py: an
explicit, opt-in operation rather than something wired into the live app).
"""

import argparse
import asyncio
import datetime as dt

from app.db.base import AsyncSessionLocal
from app.integrations.fyers.fyers_client import FyersClient
from app.logging_config import configure_logging, get_logger
from app.services.backtest_service import DEFAULT_HOLDING_PERIOD_DAYS, run_backtest

configure_logging()
logger = get_logger(__name__)


def _parse_date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run a signal backtest for one symbol.")
    parser.add_argument("symbol", help='FYERS symbol, e.g. "NSE:RELIANCE-EQ"')
    parser.add_argument("--sector", default=None, help="Sector label for relative-strength (see app/data/universe.py)")
    parser.add_argument("--start", required=True, type=_parse_date, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_parse_date, help="YYYY-MM-DD")
    parser.add_argument("--holding-period-days", type=int, default=DEFAULT_HOLDING_PERIOD_DAYS)
    parser.add_argument("--no-persist", action="store_true", help="Don't write to the signals table")
    args = parser.parse_args()

    client = FyersClient()
    try:
        async with AsyncSessionLocal() as db:
            summary = await run_backtest(
                client, db, args.symbol, args.sector, args.start, args.end,
                holding_period_days=args.holding_period_days,
                persist_signals=not args.no_persist,
            )
    finally:
        await client.aclose()

    print(f"\n{summary.symbol}  {summary.start_date} -> {summary.end_date}  (holding {summary.holding_period_days}d)")
    print(f"Signals generated: {summary.signals_generated}   Setups evaluated: {len(summary.trades)}")

    print("\nBy setup type:")
    for setup_type, stats in sorted(summary.by_setup_type.items()):
        print(
            f"  {setup_type:32} n={stats.count:4}  hit_rate={_fmt_pct(stats.hit_rate_pct)}  "
            f"avg_return={_fmt_pct(stats.avg_forward_return_pct)}  avg_days={stats.avg_trading_days_to_outcome}"
        )

    if summary.overall:
        s = summary.overall
        print(
            f"\nOverall: n={s.count}  hit_rate={_fmt_pct(s.hit_rate_pct)}  "
            f"avg_return={_fmt_pct(s.avg_forward_return_pct)}  avg_days={s.avg_trading_days_to_outcome}"
        )


def _fmt_pct(value: float | None) -> str:
    return f"{value:.2f}%" if value is not None else "N/A"


if __name__ == "__main__":
    asyncio.run(main())
