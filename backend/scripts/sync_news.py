"""Manual/scheduled entrypoint for bulk news collection across the universe.

Run from backend/:
    python -m scripts.sync_news

Per-stock news is also collected automatically and inline whenever
/api/stocks/{symbol}/analysis or a scanner run touches that stock (see
app/services/stock_service.py -> app/services/news_service.py) -- this
script exists for pre-warming the `news` table across the whole universe on
a schedule, same pattern as scripts/sync_universe.py.
"""

import asyncio

from app.data.universe import get_seed_universe
from app.db.base import AsyncSessionLocal
from app.logging_config import configure_logging, get_logger
from app.services.news_service import get_fresh_news_for_stock
from app.services.stock_service import get_or_create_stock_row

configure_logging()
logger = get_logger(__name__)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        total_matched = 0
        for entry in get_seed_universe():
            stock_row = await get_or_create_stock_row(db, entry)
            rows = await get_fresh_news_for_stock(db, stock_row.id, entry.symbol, entry.company_name)
            logger.info("%s: %d news item(s) on file", entry.symbol, len(rows))
            total_matched += len(rows)

        await db.commit()

    logger.info("News sync complete: %d total item(s) across the universe", total_matched)


if __name__ == "__main__":
    asyncio.run(main())
