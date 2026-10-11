"""Operator entrypoint for the Phase D MTF daily collection.

Run from backend/ (inside the api container):
    python -m scripts.run_mtf_collection status
    python -m scripts.run_mtf_collection scan --session-date 2026-09-29 [--live] [--force]
    python -m scripts.run_mtf_collection generate --session-date 2026-09-30 [--live] [--force]

Without --force a stage that already ran for that session is refused (the
same UNIQUE dedup key the scheduler uses). --force records a separate,
explicitly forced run. Dry-run unless --live. Never places orders.
"""

import argparse
import asyncio
import datetime as dt
import json

from app.config import get_settings
from app.logging_config import configure_logging
from app.services.mtf_daily_collection_service import (
    STAGE_GENERATE,
    STAGE_SCAN,
    MtfDailyCollector,
    dedup_key,
)

configure_logging()


async def main() -> None:
    parser = argparse.ArgumentParser(description="MTF daily evidence collection (operator)")
    parser.add_argument("action", choices=["status", "scan", "generate"])
    parser.add_argument("--session-date", type=dt.date.fromisoformat)
    parser.add_argument("--live", action="store_true", help="persist suggestions (default: dry-run)")
    parser.add_argument("--force", action="store_true", help="run even if this stage already ran")
    args = parser.parse_args()

    settings = get_settings().model_copy(update={"mtf_daily_collection_dry_run": not args.live})
    collector = MtfDailyCollector(settings=settings)
    if args.action == "status":
        print(json.dumps(await collector.status(), default=str, indent=1))
        return
    if args.session_date is None:
        parser.error("--session-date is required")
    stage = STAGE_SCAN if args.action == "scan" else STAGE_GENERATE
    if not args.force:
        async with collector._session() as db:
            done, _ = await collector._existing(db, stage, args.session_date)
        if done is not None:
            print(f"refused: {dedup_key(stage, args.session_date, not args.live)} already ran (run {done.id}, "
                  f"{done.status}); pass --force to record a forced re-run")
            return
    runner = collector.run_scan if stage == STAGE_SCAN else collector.run_generate
    print(json.dumps(await runner(args.session_date, forced=args.force), default=str))


if __name__ == "__main__":
    asyncio.run(main())
