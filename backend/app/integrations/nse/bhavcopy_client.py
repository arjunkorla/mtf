"""Fetches NSE's official daily "securities bhavcopy" CSV -- the only free
EOD source for delivery quantity/percentage per symbol (section 9's
"delivery data" proxy).

Confirmed real, public, no-auth endpoint (2026-09-19):
    https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv

This is the bulk-archive subdomain, NOT the live nseindia.com JSON API --
that one returns HTTP 403 to any non-browser client even with a primed
session (see app/integrations/news/rss_feed_client.py's module docstring for
that finding). The archive answered directly with just browser-like headers,
no cookie priming needed, confirmed with a live fetch that included a real
header row (SYMBOL, SERIES, DATE1, ..., DELIV_QTY, DELIV_PER) -- a genuine
documented schema, not inferred column positions.

NSE only publishes a file for actual trading days -- a non-trading date
(weekend/holiday/future) returns HTTP 404 (confirmed live), so callers walk
backward from a given date to find the most recent published file.
"""

import datetime as dt

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import MtfError
from app.logging_config import get_logger

logger = get_logger(__name__)

BHAVCOPY_URL_TEMPLATE = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
MAX_BACKWARD_DAYS = 7  # enough to skip a long weekend + a holiday or two

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# Real rows captured from a live fetch (2026-09-19) covering a mix of
# large-caps with distinct delivery percentages, so mock-mode development
# and tests work without network access.
_MOCK_BHAVCOPY_CSV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
20MICRONS, EQ, 18-Sep-2026, 205.71, 207.77, 209.00, 204.62, 206.50, 208.28, 207.02, 45744, 94.70, 1711, 21567, 47.15
RELIANCE, EQ, 18-Sep-2026, 1243.90, 1245.00, 1247.30, 1226.40, 1226.40, 1226.40, 1234.75, 15122715, 186728.32, 162092, 11645440, 77.01
TCS, EQ, 18-Sep-2026, 2190.00, 2177.20, 2177.30, 2101.20, 2105.00, 2105.00, 2117.95, 6875428, 145618.29, 188367, 3972356, 57.78
HDFCBANK, EQ, 18-Sep-2026, 713.00, 715.25, 733.80, 715.25, 731.00, 731.00, 728.00, 39400710, 286838.51, 281343, 25195213, 63.95
INFY, EQ, 18-Sep-2026, 1058.60, 1061.90, 1061.90, 1038.00, 1051.40, 1051.40, 1047.93, 22124953, 231854.51, 133181, 15755453, 71.21
"""


async def _fetch_one_date(client: httpx.AsyncClient, date: dt.date) -> str | None:
    url = BHAVCOPY_URL_TEMPLATE.format(date=date.strftime("%d%m%Y"))
    try:
        resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
    except httpx.TransportError as exc:
        raise MtfError(f"Failed to fetch NSE bhavcopy for {date}: {exc}") from exc

    if resp.status_code == 404:
        return None  # not a trading day, or not yet published
    if resp.status_code >= 400:
        raise MtfError(f"NSE bhavcopy fetch failed for {date}: HTTP {resp.status_code}")
    return resp.text


async def fetch_latest_bhavcopy_csv(settings: Settings | None = None, as_of: dt.date | None = None) -> tuple[str, dt.date]:
    """Returns (csv_text, actual_trading_date). Walks backward from `as_of`
    (default today) up to MAX_BACKWARD_DAYS to find the most recent
    published file.
    """
    settings = settings or get_settings()

    if settings.use_mock_fyers:
        return _MOCK_BHAVCOPY_CSV, dt.date(2026, 9, 18)

    anchor = as_of or dt.date.today()
    async with httpx.AsyncClient(timeout=20.0) as client:
        for offset in range(MAX_BACKWARD_DAYS):
            candidate_date = anchor - dt.timedelta(days=offset)
            csv_text = await _fetch_one_date(client, candidate_date)
            if csv_text is not None:
                return csv_text, candidate_date

    raise MtfError(f"No NSE bhavcopy found in the last {MAX_BACKWARD_DAYS} days back from {anchor}")
