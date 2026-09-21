"""Orchestrates the research confirmation layer (Phase 5): combines an
already-computed CandidateResponse + RealtimeConfirmationResponse with the
newly verified research sources (India VIX, global macro) into a
ResearchConfirmation. Never recomputes candidate/confirmation evidence
itself -- only reads what the existing production services already built.
"""

import datetime as dt

from app.data.normalization import normalize_india_vix
from app.engines.global_macro_engine import build_global_macro_context
from app.engines.research_confirmation_engine import build_india_vix_context, build_research_confirmation
from app.integrations.fyers.fyers_client import FyersClient
from app.logging_config import get_logger
from app.schemas.research import ResearchConfirmation
from app.schemas.scanner import CandidateResponse
from app.services.fno_service import _get_cached_options_chain
from app.services.global_macro_service import get_global_macro_snapshot
from app.services.realtime_confirmation_service import get_realtime_confirmation

logger = get_logger(__name__)

# A single, always-available underlying used ONLY to extract the
# market-wide India VIX value that rides along on any options-chain
# response (see app/data/normalization.py's normalize_india_vix) -- fixed
# and shared across every candidate in a run so it resolves to ONE cached
# fetch (fno_service's own options_chain_key/TTL_FNO_SECONDS) rather than
# one per candidate (Phase 5 Step 13 anti-duplication requirement). Reuses
# fno_service's existing private caching helper as-is -- no production file
# is modified to get this reuse.
_VIX_PROXY_UNDERLYING = "NSE:NIFTY50-INDEX"


async def _fetch_india_vix(client: FyersClient) -> tuple[float | None, str | None]:
    try:
        raw = await _get_cached_options_chain(client, _VIX_PROXY_UNDERLYING)
    except Exception as exc:  # noqa: BLE001 -- a VIX outage must not sink the whole research call
        logger.warning("India VIX fetch failed via %s: %s", _VIX_PROXY_UNDERLYING, exc)
        return None, None
    vix = normalize_india_vix(raw)
    source = "FYERS options-chain (India VIX rides along, confirmed live 2026-09-21)" if vix is not None else None
    return vix, source


async def build_research_confirmation_for_candidate(candidate: CandidateResponse, client: FyersClient) -> ResearchConfirmation:
    realtime = None
    try:
        realtime = await get_realtime_confirmation(candidate.symbol, candidate, client)
    except Exception as exc:  # noqa: BLE001 -- research layer degrades, never breaks, on a confirmation-engine outage
        logger.warning("Real-time confirmation unavailable for %s: %s", candidate.symbol, exc)

    macro_quotes = await get_global_macro_snapshot()
    macro_context = build_global_macro_context(macro_quotes, candidate.sector)

    now = dt.datetime.now(dt.UTC)
    vix, vix_source = await _fetch_india_vix(client)
    vix_context = build_india_vix_context(vix, now if vix is not None else None, vix_source)

    return build_research_confirmation(candidate, realtime, macro_context, vix_context, now=now)
