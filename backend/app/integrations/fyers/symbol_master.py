"""Fetches the FYERS NSE Capital Market symbol-master CSV.

Confirmed real, public, no-auth endpoint (FYERS community documentation,
verified 2026-09-19): https://public.fyers.in/sym_details/NSE_CM.csv. This
is a different host than the authenticated trading/data APIs in
fyers_client.py, so it gets its own tiny adapter rather than going through
FyersClient's auth headers.
"""

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import FyersApiError
from app.logging_config import get_logger

logger = get_logger(__name__)

SYMBOL_MASTER_URL = "https://public.fyers.in/sym_details/NSE_CM.csv"

# A handful of real rows (captured from a live fetch) covering both the
# common EQ series and an mtf_tradable=0 case, so parser/importer tests and
# USE_MOCK_FYERS=true development runs don't need network access.
_MOCK_CSV = """101000000016921,20 MICRONS LTD,0,1,0.01,INE144J01027,0915-1530|1815-1915:,2026-09-18,,NSE:20MICRONS-EQ,10,10,16921,20MICRONS,16921,-1.0,XX,101000000016921,None,1,2.0
10100000004,21ST CENTURY MGMT SERVICE,0,1,0.01,INE253B01015,0915-1530|1815-1915:,2026-09-18,,NSE:21STCENMGM-EQ,10,10,4,21STCENMGM,4,-1.0,XX,10100000004,None,0,0.0
101000000013061,360 ONE WAM LIMITED,0,1,0.1,INE466L01038,0915-1530|1815-1915:,2026-09-18,,NSE:360ONE-EQ,10,10,13061,360ONE,13061,-1.0,XX,101000000013061,None,1,3.2
10100000006240,3I INFOTECH LIMITED,0,1,0.01,INE748C01038,0915-1530|1815-1915:,2026-09-18,,NSE:3IINFOLTD-BE,10,10,6240,3IINFOLTD,6240,-1.0,XX,10100000006240,None,0,0.0
"""


async def fetch_symbol_master_csv(settings: Settings | None = None) -> str:
    settings = settings or get_settings()

    if settings.use_mock_fyers:
        logger.info("Using mock NSE symbol-master CSV (USE_MOCK_FYERS=true)")
        return _MOCK_CSV

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(SYMBOL_MASTER_URL)
        except httpx.TransportError as exc:
            raise FyersApiError(f"Failed to fetch NSE symbol master: {exc}") from exc

    if resp.status_code >= 400:
        raise FyersApiError(f"NSE symbol master fetch failed: HTTP {resp.status_code}")

    return resp.text
