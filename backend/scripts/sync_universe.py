"""Manual/scheduled entrypoint for the NSE symbol-master sync (section 5).

Run from backend/:
    python -m scripts.sync_universe

Intended to be run periodically (FYERS updates the symbol master roughly
daily) via cron/Task Scheduler once you're ready to scan a wider universe
than the 20-stock development seed list -- see
app/services/universe_sync_service.py for why this isn't wired into the
scanner automatically.
"""

import asyncio

from app.db.base import AsyncSessionLocal
from app.logging_config import configure_logging, get_logger
from app.services.universe_sync_service import sync_universe_from_fyers

configure_logging()
logger = get_logger(__name__)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        summary = await sync_universe_from_fyers(db)

    logger.info(
        "Sync summary: %d rows seen, %d skipped, %d inserted, %d updated",
        summary.rows_seen, summary.rows_skipped, summary.inserted, summary.updated,
    )
    if summary.skip_reasons_sample:
        logger.info("Sample skip reasons: %s", summary.skip_reasons_sample)


if __name__ == "__main__":
    asyncio.run(main())
