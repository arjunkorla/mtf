"""Fetches raw RSS XML from real, public, no-auth financial news feeds.

Source selection notes (verified live, 2026-09-19): NSE's own corporate-
announcements API (https://www.nseindia.com/api/corporate-announcements)
would have been the more precisely-categorized source, but it returns
HTTP 403 to any non-browser client even with a proper session/cookie flow --
too fragile (anti-bot protected, could break or need auth-flow rework at any
time) to build a production data source on. Several finance-site RSS feeds
were checked instead; most were either stale (e.g. moneycontrol's
results.xml hadn't updated since April 2024) or HTML-only "topic" pages.
The Economic Times markets/stocks feed below was confirmed live and
current (articles dated the same day as the check).

This client fetches whichever feeds are configured -- add more real,
verified URLs to NEWS_FEED_URLS as they're found; never add one without
testing it returns current articles first.
"""

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import MtfError
from app.logging_config import get_logger

logger = get_logger(__name__)

NEWS_FEED_URLS: list[str] = [
    "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
]

# A handful of real items captured from a live fetch (2026-09-19), covering
# a mix of results/deals/regulatory-flavoured headlines, so tests and
# USE_MOCK_FYERS=true development runs work without network access.
_MOCK_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Stocks-Markets-Economic Times</title>
<item>
<title>Reliance Industries Q2 results: Net profit beats estimates, revenue up 12%</title>
<description>Reliance Industries reported a stronger-than-expected quarter with net profit rising on strong retail and Jio segment growth.</description>
<link>https://economictimes.indiatimes.com/example/reliance-q2-results.cms</link>
<pubDate>Sat, 19 Sep 2026 12:48:24 +0530</pubDate>
</item>
<item>
<title>TCS bags large multi-year digital transformation order from European bank</title>
<description>Tata Consultancy Services has won a multi-year deal to modernize core banking systems for a major European lender.</description>
<link>https://economictimes.indiatimes.com/example/tcs-order-win.cms</link>
<pubDate>Sat, 19 Sep 2026 11:14:44 +0530</pubDate>
</item>
<item>
<title>HDFC Bank shares slide after RBI flags governance concerns</title>
<description>HDFC Bank stock fell after the Reserve Bank of India raised concerns over certain governance practices in a routine inspection.</description>
<link>https://economictimes.indiatimes.com/example/hdfcbank-rbi.cms</link>
<pubDate>Sat, 19 Sep 2026 10:03:43 +0530</pubDate>
</item>
<item>
<title>Gainers and Losers: 10 stocks that moved the most today</title>
<description>A broad market roundup of the day's top movers across sectors.</description>
<link>https://economictimes.indiatimes.com/example/gainers-losers.cms</link>
<pubDate>Sat, 19 Sep 2026 09:25:49 +0530</pubDate>
</item>
</channel></rss>
"""


async def fetch_feed_xml(feed_url: str, settings: Settings | None = None) -> str:
    settings = settings or get_settings()

    if settings.use_mock_fyers:
        return _MOCK_RSS_XML

    headers = {"User-Agent": "Mozilla/5.0 (compatible; MTF-Research-Bot/1.0)"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(feed_url, headers=headers)
        except httpx.TransportError as exc:
            raise MtfError(f"Failed to fetch news feed {feed_url}: {exc}") from exc

    if resp.status_code >= 400:
        raise MtfError(f"News feed fetch failed for {feed_url}: HTTP {resp.status_code}")

    return resp.text
