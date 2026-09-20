"""Fetches the FYERS NSE Futures & Options symbol-master CSV.

Confirmed real, public, no-auth endpoint (verified live 2026-09-20, same
public host and column layout as symbol_master.py's NSE_CM.csv fetch):
https://public.fyers.in/sym_details/NSE_FO.csv. Needed because FYERS
futures contract symbols roll monthly (e.g. NSE:RELIANCE26SEPFUT ->
NSE:RELIANCE26OCTFUT) and are not safely derivable from a pattern -- see
app/data/fo_symbol_master_parser.py, which resolves the current near-month
contract per underlying from this file.
"""

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import FyersApiError
from app.logging_config import get_logger

logger = get_logger(__name__)

FO_SYMBOL_MASTER_URL = "https://public.fyers.in/sym_details/NSE_FO.csv"

# Real rows captured from a live fetch (2026-09-20), covering one underlying
# (RELIANCE) with three rolling monthly contracts, so parser tests and
# USE_MOCK_FYERS=true development runs don't need network access.
_MOCK_CSV = """101126092968777,RELIANCE 29 Sep 26 FUT,13,500,0.1,,0915-1540|1815-1915:,2026-09-18,1790676600,NSE:RELIANCE26SEPFUT,10,11,68777,RELIANCE,2885,-1.0,XX,10100000002885,None,0,0.0
101126102748987,RELIANCE 27 Oct 26 FUT,13,500,0.1,,0915-1540|1815-1915:,2026-09-18,1793095800,NSE:RELIANCE26OCTFUT,10,11,48987,RELIANCE,2885,-1.0,XX,10100000002885,None,0,0.0
101126112361697,RELIANCE 23 Nov 26 FUT,13,500,0.1,,0915-1540|1815-1915:,2026-09-18,1795428600,NSE:RELIANCE26NOVFUT,10,11,61697,RELIANCE,2885,-1.0,XX,10100000002885,None,0,0.0
"""


async def fetch_fo_symbol_master_csv(settings: Settings | None = None) -> str:
    settings = settings or get_settings()

    if settings.use_mock_fyers:
        logger.info("Using mock NSE F&O symbol-master CSV (USE_MOCK_FYERS=true)")
        return _MOCK_CSV

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(FO_SYMBOL_MASTER_URL)
        except httpx.TransportError as exc:
            raise FyersApiError(f"Failed to fetch NSE F&O symbol master: {exc}") from exc

    if resp.status_code >= 400:
        raise FyersApiError(f"NSE F&O symbol master fetch failed: HTTP {resp.status_code}")

    return resp.text
