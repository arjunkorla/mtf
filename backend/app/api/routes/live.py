"""WebSocket /api/ws/quotes -- Phase 5 live quote streaming (section 30),
re-architected in the Phase 2/3 shared-hub work: every connected client is
now backed by the SAME process-wide FYERS WebSocket connection
(app/services/live_data_hub.py), reference-counted per symbol. Multiple
browser tabs watching the same symbol no longer refuse each other, and each
one only affects its own symbols on disconnect.

Not part of the original 8-endpoint REST contract (section 21); the
frontend is not wired to this yet. It's additive backend infrastructure a
client can opt into with a native WebSocket connection when wanted.

Known limitation: if FYERS_CLIENT_ID/FYERS_ACCESS_TOKEN aren't set and
USE_MOCK_FYERS=false, the underlying feed thread logs an error and simply
never produces ticks -- the connection stays open but silent rather than
erroring, since there's no live-side signal to distinguish "slow market"
from "misconfigured" without guessing.
"""

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.logging_config import get_logger
from app.services.live_quote_service import LiveQuoteHub

logger = get_logger(__name__)

router = APIRouter()


@router.websocket("/ws/quotes")
async def stream_quotes(websocket: WebSocket, symbols: str = Query(..., description="Comma-separated FYERS symbols")):
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        await websocket.close(code=1008, reason="At least one symbol is required")
        return

    await websocket.accept()

    hub = LiveQuoteHub(symbol_list)
    hub.start()
    logger.info("Live quote WebSocket opened for %s", symbol_list)

    try:
        while True:
            tick = await hub.next_tick()
            await websocket.send_json(tick)
    except WebSocketDisconnect:
        pass
    finally:
        hub.stop()
        logger.info("Live quote WebSocket closed for %s", symbol_list)
