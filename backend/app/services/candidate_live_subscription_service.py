"""Dynamically subscribes the scanner's current candidates through the
EXISTING shared LiveDataHub (Phase 6 Objective 1) so the research layer can
get live quotes even when nobody has the frontend stock-detail page open.

Deliberately does not modify LiveDataHub or its reference-counting at all --
that class was already built for exactly this multi-consumer pattern (see
its own module docstring). This module only USES subscribe()/unsubscribe()
correctly:
  - One process-wide FYERS WebSocket (LiveDataHub's own singleton, unchanged).
  - No WebSocket per stock, no WebSocket per caller -- every symbol shares
    the one underlying FyersMarketDataSocket connection.
  - Reference counting is entirely LiveDataHub's: a symbol a real frontend
    client already has open keeps its own refcount from this subscribe()
    call, and unsubscribe() here only ever decrements OUR reference -- the
    frontend's subscription is untouched regardless of what this module does.
  - subscribe()/unsubscribe() are called in a try/finally, so an exception
    partway through a scan can never leak a dangling subscription.

The scanner itself never calls this -- it's used only by the observation
collection orchestrator (research_snapshot_service.py), so
POST /api/scanner/run remains fully independent of WebSocket availability.
"""

import asyncio

from app.config import Settings, get_settings
from app.services.live_data_hub import live_data_hub
from app.services.market_data_service import get_cached_live_quote


async def collect_live_quotes_for_candidates(
    symbols: list[str], settle_seconds: float | None = None, settings: Settings | None = None,
) -> dict[str, dict | None]:
    """Subscribes `symbols`, waits `settle_seconds` for real ticks to reach
    the shared Redis live-quote cache, then reads whatever arrived --
    unsubscribing afterwards regardless of outcome. A symbol with no tick in
    the window returns None (honest "no live data yet"), never a fabricated
    value -- FYERS litemode only pushes on an actual trade, so an illiquid
    moment can genuinely produce nothing."""
    if not symbols:
        return {}

    settings = settings or get_settings()
    settle = settle_seconds if settle_seconds is not None else settings.live_subscription_settle_seconds

    subscriber_id, _queue = live_data_hub.subscribe(symbols)
    try:
        if settle > 0:
            await asyncio.sleep(settle)
        return {symbol: await get_cached_live_quote(symbol) for symbol in symbols}
    finally:
        live_data_hub.unsubscribe(subscriber_id, symbols)
