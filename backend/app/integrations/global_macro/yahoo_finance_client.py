"""Fetches global market/macro quotes from Yahoo Finance's chart endpoint.

Confirmed live 2026-09-21: `https://query1.finance.yahoo.com/v8/finance/chart/<symbol>`
returns real, current values with no authentication for major indices,
commodities, forex, and yields (S&P 500, Nasdaq, Dow, Nikkei 225, Hang Seng,
WTI/Brent crude, gold, USD/INR, US 10Y yield). GIFT Nifty has no confirmed
Yahoo ticker and is deliberately NOT in MACRO_SYMBOLS -- not guessed at.

IMPORTANT -- this is an unofficial, undocumented API, not a licensed Yahoo
data feed: there is no published contract that it will keep working, keep
this shape, or stay unthrottled, and Yahoo's terms of service don't clearly
cover this kind of automated pull. Kept anyway as an explicit, user-approved
best-effort source (no free/licensed alternative was found for this project)
-- every consumer of this data must carry `MacroQuote.source`
(app/data/global_macro_parser.py) so it's never presented as an authoritative
feed. If this endpoint starts failing/blocking, that's expected risk
materializing, not a bug to route around with a scraper.

A fetch failure for one symbol must never break the others (see
global_macro_service.py) -- each request is independent.
"""

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import MtfError
from app.logging_config import get_logger

logger = get_logger(__name__)

CHART_URL_TEMPLATE = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# label -> Yahoo Finance ticker. Every one of these was confirmed live
# 2026-09-21 to return a real, current regularMarketPrice.
MACRO_SYMBOLS: dict[str, str] = {
    "S&P 500": "^GSPC",
    "Nasdaq": "^IXIC",
    "Dow Jones": "^DJI",
    "Nikkei 225": "^N225",
    "Hang Seng": "^HSI",
    "WTI Crude": "CL=F",
    "Brent Crude": "BZ=F",
    "Gold": "GC=F",
    "USD/INR": "INR=X",
    "US 10Y Yield": "^TNX",
}

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

# Real values captured from a live fetch (2026-09-21) for mock-mode
# development and tests without network access.
_MOCK_CHART_RESPONSES: dict[str, dict] = {
    "^GSPC": {"chart": {"result": [{"meta": {
        "symbol": "^GSPC", "regularMarketPrice": 7650.5, "regularMarketChangePercent": 0.167,
        "chartPreviousClose": 7637.76, "regularMarketTime": 1789766988,
    }}]}},
    "^IXIC": {"chart": {"result": [{"meta": {
        "symbol": "^IXIC", "regularMarketPrice": 26522.545, "regularMarketChangePercent": 0.395,
        "chartPreviousClose": 26418.3, "regularMarketTime": 1789766159,
    }}]}},
    "^DJI": {"chart": {"result": [{"meta": {
        "symbol": "^DJI", "regularMarketPrice": 51682.64, "regularMarketChangePercent": -0.181,
        "chartPreviousClose": 51778.0, "regularMarketTime": 1789768347,
    }}]}},
    "^N225": {"chart": {"result": [{"meta": {
        "symbol": "^N225", "regularMarketPrice": 65018.95, "regularMarketChangePercent": 1.376,
        "chartPreviousClose": 64136.2, "regularMarketTime": 1789713903,
    }}]}},
    "^HSI": {"chart": {"result": [{"meta": {
        "symbol": "^HSI", "regularMarketPrice": 24906.51, "regularMarketChangePercent": 0.629,
        "chartPreviousClose": 24750.78, "regularMarketTime": 1789970806,
    }}]}},
    "CL=F": {"chart": {"result": [{"meta": {
        "symbol": "CL=F", "regularMarketPrice": 94.51, "regularMarketChangePercent": -1.634,
        "chartPreviousClose": 96.08, "regularMarketTime": 1789971091,
    }}]}},
    "BZ=F": {"chart": {"result": [{"meta": {
        "symbol": "BZ=F", "regularMarketPrice": 97.9, "regularMarketChangePercent": -1.4,
        "chartPreviousClose": 99.29, "regularMarketTime": 1789971006,
    }}]}},
    "GC=F": {"chart": {"result": [{"meta": {
        "symbol": "GC=F", "regularMarketPrice": 4391.0, "regularMarketChangePercent": -0.766,
        "chartPreviousClose": 4424.9, "regularMarketTime": 1789971105,
    }}]}},
    "INR=X": {"chart": {"result": [{"meta": {
        "symbol": "INR=X", "regularMarketPrice": 95.81, "regularMarketChangePercent": -0.055,
        "chartPreviousClose": 95.863, "regularMarketTime": 1789971706,
    }}]}},
    "^TNX": {"chart": {"result": [{"meta": {
        "symbol": "^TNX", "regularMarketPrice": 4.998, "regularMarketChangePercent": 1.031,
        "chartPreviousClose": 4.947, "regularMarketTime": 1789757995,
    }}]}},
}


async def fetch_macro_chart(ticker: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()

    if settings.use_mock_fyers:
        return _MOCK_CHART_RESPONSES.get(ticker, {"chart": {"result": None}})

    headers = {"User-Agent": _USER_AGENT}
    url = CHART_URL_TEMPLATE.format(symbol=ticker)
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(url, params={"range": "1d", "interval": "1d"}, headers=headers)
        except httpx.TransportError as exc:
            raise MtfError(f"Failed to fetch macro quote for {ticker}: {exc}") from exc

    if resp.status_code >= 400:
        raise MtfError(f"Macro quote fetch failed for {ticker}: HTTP {resp.status_code}")

    return resp.json()
