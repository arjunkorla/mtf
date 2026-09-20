"""News/catalyst collection (section 13) -- Phase 2.

Fetches real, configured RSS feeds (app/integrations/news/rss_feed_client.py),
matches items against one stock by ticker/company-name substring, and
upserts genuine matches into the `news` table. app/engines/news_engine.py
(unchanged) then reads from that table exactly as it always has.

Never invents an article: every row this writes traces back to a title,
link, and publish date that was actually present in a fetched feed.

A feed-fetch or parse failure never breaks candidate scoring -- it's caught
here and logged; the caller falls back to whatever's already in the `news`
table (possibly nothing, which the rest of the pipeline already treats as an
honest "no catalyst data" state, not an error).
"""

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.news_matcher import RawNewsItem, classify_category, classify_sentiment, matches_company, parse_rss_feed
from app.db.redis_client import get_redis
from app.integrations.news.rss_feed_client import NEWS_FEED_URLS, fetch_feed_xml
from app.logging_config import get_logger
from app.models.news import NewsItem
from app.services.cache_service import TTL_NEWS_FEED_SECONDS, get_text, news_feed_key, set_text

logger = get_logger(__name__)

_FEED_SOURCE_LABEL = "Economic Times"


async def _get_cached_feed_items(feed_url: str) -> list[RawNewsItem]:
    redis = get_redis()
    cache_key = news_feed_key(feed_url)

    cached_xml = await get_text(redis, cache_key)
    if cached_xml is not None:
        return parse_rss_feed(cached_xml)

    raw_xml = await fetch_feed_xml(feed_url)
    await set_text(redis, cache_key, raw_xml, TTL_NEWS_FEED_SECONDS)
    return parse_rss_feed(raw_xml)


async def _fetch_all_feed_items() -> list[RawNewsItem]:
    items: list[RawNewsItem] = []
    for feed_url in NEWS_FEED_URLS:
        try:
            items.extend(await _get_cached_feed_items(feed_url))
        except Exception as exc:  # noqa: BLE001 -- one bad feed must not sink the others
            logger.warning("News feed fetch/parse failed for %s: %s", feed_url, exc)
    return items


async def _upsert_matched_items(db: AsyncSession, stock_id: int, matched: list[RawNewsItem]) -> int:
    inserted = 0
    for item in matched:
        existing = (
            await db.execute(select(NewsItem).where(NewsItem.stock_id == stock_id, NewsItem.source_url == item.link))
        ).scalar_one_or_none()
        if existing is not None:
            continue

        db.add(
            NewsItem(
                stock_id=stock_id,
                headline=item.title[:512],
                summary=item.description or None,
                category=classify_category(item),
                sentiment=classify_sentiment(item),
                source=_FEED_SOURCE_LABEL,
                source_url=item.link,
                published_at=item.published_at,
                fetched_at=dt.datetime.now(dt.UTC),
            )
        )
        inserted += 1

    if inserted:
        await db.commit()
    return inserted


async def get_fresh_news_for_stock(
    db: AsyncSession, stock_id: int, symbol: str, company_name: str, limit: int = 10
) -> list[NewsItem]:
    ticker = symbol.split(":")[-1].split("-")[0]

    try:
        feed_items = await _fetch_all_feed_items()
        matched = [item for item in feed_items if matches_company(item, ticker, company_name)]
        if matched:
            inserted = await _upsert_matched_items(db, stock_id, matched)
            if inserted:
                logger.info("News sync for %s: %d new item(s) matched and stored", symbol, inserted)
    except Exception as exc:  # noqa: BLE001 -- a news outage must never break a candidate build
        logger.warning("News collection failed for %s, falling back to stored data: %s", symbol, exc)

    rows = (
        await db.execute(
            select(NewsItem)
            .where(NewsItem.stock_id == stock_id)
            .order_by(NewsItem.published_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)
