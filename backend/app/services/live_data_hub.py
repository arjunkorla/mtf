"""Shared, process-wide live market-data hub (Phase 2/3 real-time
architecture). ONE FyersMarketDataSocket backs however many symbols any
number of consumers need, with reference-counted subscriptions -- a symbol
is only unsubscribed at FYERS once its last consumer goes away.

Replaces the old per-client LiveQuoteHub design (one FyersMarketDataSocket
per browser connection), which could never actually support more than one
concurrent client anyway: the underlying FYERS SDK connection is a
process-wide singleton (see websocket.py's module docstring), so a second
client's hub could only ever be refused, not genuinely independent.

Threading/asyncio model: ticks arrive on FyersMarketDataSocket's background
thread. This process runs one asyncio event loop (the single uvicorn worker
process every deployment of this backend actually uses -- see
app/main.py/docker-compose.yml, no multi-worker config exists), so exactly
one loop is ever registered here; that assumption is asserted, not silently
relied on, so a future multi-worker deployment fails loudly instead of
routing ticks to the wrong worker's loop.
"""

import asyncio
import threading
import uuid

from app.config import Settings
from app.db.redis_client import get_redis
from app.integrations.fyers.websocket import FyersMarketDataSocket
from app.logging_config import get_logger
from app.services.cache_service import TTL_LIVE_QUOTE_SECONDS, live_quote_key, set_json

logger = get_logger(__name__)


def normalize_tick(raw: dict) -> dict:
    """Maps a raw tick (from the live SDK or the mock generator) to a
    stable output shape. Only `symbol`/`ltp` are confirmed fields for the
    live path (see websocket.py's module docstring) -- everything else is
    read defensively with `.get()`, never assumed present."""
    import datetime as dt

    return {
        "symbol": raw["symbol"],
        "ltp": float(raw["ltp"]),
        "volume": raw.get("vol_traded_today") or raw.get("volume"),
        "as_of": raw.get("timestamp") or dt.datetime.now(dt.UTC).isoformat(),
    }


class LiveDataHub:
    """One instance per process (see live_data_hub singleton below).
    Thread-safety: all mutation of _ref_counts/_subscribers/_socket happens
    under `_lock`, since subscribe()/unsubscribe() are called from asyncio
    request-handler code while _on_tick runs concurrently on the
    FyersMarketDataSocket's own background thread.
    """

    def __init__(self, settings: Settings | None = None):
        self._settings = settings
        self._lock = threading.Lock()
        self._socket: FyersMarketDataSocket | None = None
        self._ref_counts: dict[str, int] = {}
        self._subscribers: dict[str, dict[str, asyncio.Queue]] = {}  # symbol -> {subscriber_id: queue}
        self._loop: asyncio.AbstractEventLoop | None = None

    def subscriber_count(self, symbol: str) -> int:
        with self._lock:
            return self._ref_counts.get(symbol, 0)

    @property
    def active_symbols(self) -> list[str]:
        with self._lock:
            return list(self._ref_counts.keys())

    def subscribe(self, symbols: list[str]) -> tuple[str, asyncio.Queue]:
        """Registers a new consumer for `symbols`. Must be called from a
        coroutine (uses the running loop for tick delivery). Returns
        (subscriber_id, queue) -- the caller reads ticks for its own
        symbols from that queue and MUST call unsubscribe(subscriber_id,
        symbols) exactly once when done (e.g. on client disconnect)."""
        if not symbols:
            raise ValueError("symbols must be non-empty")

        loop = asyncio.get_running_loop()
        subscriber_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()

        with self._lock:
            if self._loop is None:
                self._loop = loop
            elif self._loop is not loop:
                # See module docstring: this deployment assumes one worker,
                # one loop. A second loop showing up means that assumption
                # broke -- fail loudly rather than silently dropping ticks
                # for the wrong subscribers.
                raise RuntimeError(
                    "LiveDataHub received a subscribe() call from a different event loop than "
                    "the one it started on -- this hub assumes a single-worker process; a "
                    "multi-worker deployment needs a different design (e.g. a pub/sub relay), "
                    "not a silent extension of this one."
                )

            new_symbols = []
            for symbol in symbols:
                self._subscribers.setdefault(symbol, {})[subscriber_id] = queue
                self._ref_counts[symbol] = self._ref_counts.get(symbol, 0) + 1
                if self._ref_counts[symbol] == 1:
                    new_symbols.append(symbol)

            if self._socket is None:
                self._socket = FyersMarketDataSocket(
                    symbols=list(symbols), on_tick=self._on_tick, settings=self._settings
                )
                self._socket.start()
            elif new_symbols:
                self._socket.add_symbols(new_symbols)

        logger.info(
            "[HUB_SUBSCRIBE] subscriber=%s symbols=%s total_active_symbols=%s",
            subscriber_id, symbols, list(self._ref_counts.keys()),
        )
        return subscriber_id, queue

    def unsubscribe(self, subscriber_id: str, symbols: list[str]) -> None:
        """Idempotent: safe to call with symbols already removed, or twice
        for the same subscriber_id."""
        with self._lock:
            symbols_to_remove = []
            for symbol in symbols:
                subs = self._subscribers.get(symbol)
                if not subs or subscriber_id not in subs:
                    continue
                del subs[subscriber_id]
                self._ref_counts[symbol] = max(0, self._ref_counts.get(symbol, 1) - 1)
                if self._ref_counts[symbol] <= 0:
                    symbols_to_remove.append(symbol)
                    self._ref_counts.pop(symbol, None)
                    self._subscribers.pop(symbol, None)
                elif not subs:
                    self._subscribers.pop(symbol, None)

            if symbols_to_remove and self._socket is not None:
                self._socket.remove_symbols(symbols_to_remove)

            socket_to_stop = None
            if not self._ref_counts and self._socket is not None:
                socket_to_stop = self._socket
                self._socket = None
                # Nothing is subscribed anymore -- release the loop binding
                # too, so the next subscriber (which may be a genuinely new
                # loop, e.g. after a full idle period) isn't rejected by the
                # single-loop guard in subscribe() for no real reason.
                self._loop = None

        # stop() blocks briefly (SDK thread joins) -- do it outside the lock
        # so a concurrent subscribe() for a *different* symbol isn't stalled
        # waiting on this shutdown.
        if socket_to_stop is not None:
            socket_to_stop.stop()

        logger.info(
            "[HUB_UNSUBSCRIBE] subscriber=%s symbols=%s remaining_active_symbols=%s",
            subscriber_id, symbols, list(self._ref_counts.keys()),
        )

    def _on_tick(self, raw_tick: dict) -> None:
        """Runs on FyersMarketDataSocket's background thread -- must not
        touch asyncio objects directly, only hand off via
        run_coroutine_threadsafe."""
        try:
            tick = normalize_tick(raw_tick)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Dropping malformed tick %r: %s", raw_tick, exc)
            return

        symbol = tick["symbol"]
        with self._lock:
            loop = self._loop
            queues = list(self._subscribers.get(symbol, {}).values())

        if loop is None:
            return  # no subscriber has ever registered a loop yet

        for queue in queues:
            asyncio.run_coroutine_threadsafe(queue.put(tick), loop)

        asyncio.run_coroutine_threadsafe(self._cache_latest(tick), loop)

    async def _cache_latest(self, tick: dict) -> None:
        redis = get_redis()
        await set_json(redis, live_quote_key(tick["symbol"]), tick, TTL_LIVE_QUOTE_SECONDS)


# Process-wide singleton -- the whole point of this module (see docstring).
live_data_hub = LiveDataHub()
