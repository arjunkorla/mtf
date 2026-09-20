"""Bridges the shared LiveDataHub into asyncio for one connected FastAPI
WebSocket client (section 30, Phase 5; re-architected in the Phase 2/3
shared-hub work).

Each LiveQuoteHub instance is now a thin per-client handle onto the single
process-wide LiveDataHub -- it no longer owns a FyersMarketDataSocket
itself. This is what makes "multiple frontend clients, one FYERS
connection" possible: the shared hub reference-counts symbols across every
LiveQuoteHub instance, so two clients both watching NSE:RELIANCE-EQ result
in exactly one FYERS-level subscription, and disconnecting one client
never affects the other's stream.
"""

from app.services.live_data_hub import LiveDataHub, live_data_hub


class LiveQuoteHub:
    def __init__(self, symbols: list[str], hub: LiveDataHub | None = None):
        self._symbols = symbols
        self._hub = hub or live_data_hub
        self._subscriber_id: str | None = None
        self._queue = None

    def start(self) -> None:
        self._subscriber_id, self._queue = self._hub.subscribe(self._symbols)

    def stop(self) -> None:
        if self._subscriber_id is not None:
            self._hub.unsubscribe(self._subscriber_id, self._symbols)
            self._subscriber_id = None

    async def next_tick(self) -> dict:
        return await self._queue.get()
