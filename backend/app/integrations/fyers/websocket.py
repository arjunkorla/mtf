"""FYERS live market-data WebSocket adapter -- Phase 5.

Wraps the OFFICIAL `fyers-apiv3` SDK's FyersDataSocket for the live path.
FYERS does not publicly document the WebSocket wire format -- confirmed via
their own support KB (2026-09-19): "Direct details on the WebSocket message
or packet structure for API v3 are not provided." Hand-rolling the binary
framing would mean guessing at struct/byte layouts with no way to verify
correctness without live credentials -- a categorically worse risk than a
typical REST guess, since a wrong struct format silently produces
plausible-looking WRONG numbers instead of an obvious error. The SDK does
that decoding; this module only consumes the already-parsed dict it hands
to on_message.

`fyers-apiv3` is imported lazily, inside _run_live(), specifically so
mock-mode development and the test suite never need it installed.

Confirmed live-tick fields (verified against a real connected account,
2026-09-20): `symbol`, `ltp`, `type`.

Lifecycle correctness (2026-09-20 audit + fix): `data_ws.FyersDataSocket` is
a process-wide singleton -- confirmed by reading the installed SDK's source
(`__new__` returns `cls._instance`, created once per process and reused
forever after). Two consequences, verified directly against the SDK source
for the pinned fyers-apiv3==3.1.18:

1. `stop()` must call the SDK's own `close_connection()` (a real, existing
   method -- confirmed via `inspect.getsource`, not invented) rather than
   only stopping our own polling thread. `close_connection()` sets
   `restart_flag = False` (the same flag `on_close()` checks before
   attempting an automatic reconnect) *before* tearing anything down, then
   closes the real socket and `.join()`s the SDK's own ws/message/ping
   threads. Without this, a "stopped" wrapper left the real connection
   alive in the background, auto-reconnecting indefinitely -- confirmed
   live: it kept reconnecting for minutes after `stop()` reported success,
   and the process never exited on its own (non-daemon SDK threads).

2. Because the underlying SDK object is a singleton, two independent
   `FyersMarketDataSocket` instances both running _run_live() concurrently
   would silently reconfigure (steal) the SAME shared connection's
   callbacks out from under each other -- calling the constructor again
   re-runs `__init__` on the existing singleton instance, not a fresh one.
   The smallest correct fix (not a broader redesign of LiveQuoteHub's
   one-subscription-per-client model) is a process-wide guard: only one
   *live* (non-mock) FyersMarketDataSocket may be active at a time. A
   second concurrent live start() is refused with a clear error rather
   than silently corrupting the first one's connection. Mock mode is
   unaffected (it never touches the real SDK singleton). If genuine
   concurrent live subscriptions are needed later, that requires either a
   shared multi-symbol connection (the SDK supports subscribing additional
   symbols on one connection) or confirming the SDK supports multiple
   independent instances some other way -- an intentionally separate,
   bigger decision, not made here.
"""

import datetime as dt
import random
import threading
from collections.abc import Callable

from app.config import Settings, get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

TickCallback = Callable[[dict], None]

# Process-wide guard for the live (non-mock) SDK singleton -- see module
# docstring point 2. Never touched in mock mode.
_live_socket_lock = threading.Lock()
_active_live_owner: "FyersMarketDataSocket | None" = None


class FyersMarketDataSocket:
    """One subscription's worth of live ticks for `symbols`, delivered on a
    background thread via `on_tick`.

    Threading contract: `start()`/`stop()` are safe to call from the asyncio
    event loop thread. `on_tick` itself runs ON THE BACKGROUND THREAD and
    must never touch asyncio objects directly -- use
    asyncio.run_coroutine_threadsafe from inside it to reach the event loop
    (see app/services/live_quote_service.py, the only intended caller).

    Note: in live mode, `stop()` now calls the underlying SDK's
    close_connection(), which blocks briefly (typically well under a
    second) while it joins the SDK's own background threads -- an accepted,
    bounded trade-off for actually guaranteeing the connection and its
    threads are gone before stop() returns, per the lifecycle-correctness
    fix described in the module docstring.
    """

    def __init__(self, symbols: list[str], on_tick: TickCallback, settings: Settings | None = None):
        if not symbols:
            raise ValueError("symbols must be non-empty")
        self.symbols = symbols
        self.on_tick = on_tick
        self.settings = settings or get_settings()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sdk_socket = None  # the live data_ws.FyersDataSocket instance, once started (live mode only)

    def start(self) -> None:
        logger.info("[START_REQUESTED] symbols=%s", self.symbols)

        if self._thread is not None:
            logger.info("[START_REQUESTED] ignored: already running for symbols=%s", self.symbols)
            return

        if not self.settings.use_mock_fyers:
            global _active_live_owner
            with _live_socket_lock:
                if _active_live_owner is not None and _active_live_owner is not self:
                    logger.error(
                        "[ERROR] Refusing to start live WebSocket for symbols=%s: the FYERS SDK "
                        "connection is a process-wide singleton and is already owned by another "
                        "active subscription (symbols=%s). Stop that one first.",
                        self.symbols, _active_live_owner.symbols,
                    )
                    return
                _active_live_owner = self

        target = self._run_mock if self.settings.use_mock_fyers else self._run_live
        self._thread = threading.Thread(target=target, daemon=True, name=f"fyers-ws-{','.join(self.symbols)}")
        self._thread.start()
        logger.info("[STARTED] symbols=%s", self.symbols)

    def stop(self) -> None:
        logger.info("[STOP_REQUESTED] symbols=%s", self.symbols)
        self._stop_event.set()

        if self._sdk_socket is not None:
            try:
                if self._sdk_socket.is_connected():
                    self._sdk_socket.close_connection()  # real SDK method: sets restart_flag=False,
                    # closes the socket, and joins the SDK's own ws/message/ping threads (verified
                    # via source inspection of the installed fyers-apiv3==3.1.18) -- prevents the
                    # auto-reconnect-after-stop bug found in the prior audit.
            except Exception:  # noqa: BLE001 -- a close failure must not prevent our own cleanup below
                logger.exception("[ERROR] Failed to close underlying FYERS SDK connection for symbols=%s", self.symbols)
            self._sdk_socket = None

        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

        if not self.settings.use_mock_fyers:
            global _active_live_owner
            with _live_socket_lock:
                if _active_live_owner is self:
                    _active_live_owner = None

        logger.info("[STOPPED] symbols=%s", self.symbols)

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def add_symbols(self, symbols: list[str]) -> None:
        """Adds symbols to an already-running connection without restarting
        it (Phase 3 subscription-management investigation). The real SDK's
        subscribe() is designed for incremental calls on a live connection
        -- confirmed via source inspection of fyers-apiv3==3.1.18, not
        assumed. No-op for symbols already subscribed."""
        new_symbols = [s for s in symbols if s not in self.symbols]
        if not new_symbols:
            return
        self.symbols = self.symbols + new_symbols
        logger.info("[SUBSCRIBE] adding symbols=%s (total now %s)", new_symbols, self.symbols)
        if self._sdk_socket is not None and self._sdk_socket.is_connected():
            self._sdk_socket.subscribe(symbols=new_symbols, data_type="SymbolUpdate")
        # else: not connected yet (or mock mode) -- _on_connect / _run_mock
        # will pick up the full updated self.symbols on their own.

    def remove_symbols(self, symbols: list[str]) -> None:
        """Removes symbols from an already-running connection without
        restarting it. No-op for symbols not currently subscribed."""
        to_remove = [s for s in symbols if s in self.symbols]
        if not to_remove:
            return
        self.symbols = [s for s in self.symbols if s not in to_remove]
        logger.info("[UNSUBSCRIBE] removing symbols=%s (remaining %s)", to_remove, self.symbols)
        if self._sdk_socket is not None and self._sdk_socket.is_connected():
            self._sdk_socket.unsubscribe(symbols=to_remove, data_type="SymbolUpdate")

    def _run_mock(self) -> None:
        """Synthetic ticks for local dev/tests -- same USE_MOCK_FYERS
        contract as every other integration in this project. Deliberately
        simple (small random walk), not meant to look like a real market.
        Reads self.symbols fresh each loop (rather than snapshotting once)
        so add_symbols()/remove_symbols() work in mock mode too, within
        about one wait interval."""
        prices: dict[str, float] = {}
        while not self._stop_event.is_set():
            for i, symbol in enumerate(list(self.symbols)):
                if symbol not in prices:
                    prices[symbol] = 1000.0 + i * 37.5
                prices[symbol] = max(1.0, prices[symbol] * (1 + random.uniform(-0.001, 0.0012)))
                try:
                    self.on_tick(
                        {
                            "symbol": symbol,
                            "ltp": round(prices[symbol], 2),
                            "vol_traded_today": random.randint(10_000, 50_000),
                            "timestamp": dt.datetime.now(dt.UTC).isoformat(),
                        }
                    )
                except Exception:  # noqa: BLE001 -- one bad tick handler must not kill the feed thread
                    logger.exception("on_tick handler raised for %s", symbol)
            self._stop_event.wait(timeout=1.0)

    def _run_live(self) -> None:
        from fyers_apiv3.FyersWebsocket import data_ws  # lazy: see module docstring

        if not self.settings.fyers_client_id or not self.settings.fyers_access_token:
            logger.error("[ERROR] Cannot start live FYERS WebSocket: FYERS_CLIENT_ID/FYERS_ACCESS_TOKEN not set")
            return

        access_token = f"{self.settings.fyers_client_id}:{self.settings.fyers_access_token}"
        first_tick_seen = False

        def _on_message(message: dict) -> None:
            nonlocal first_tick_seen
            if not isinstance(message, dict) or "symbol" not in message or "ltp" not in message:
                logger.debug("Ignoring unrecognized FYERS WS message shape: %r", message)
                return
            if not first_tick_seen:
                first_tick_seen = True
                logger.info("[DATA_RECEIVED] first tick received for symbols=%s", self.symbols)
            else:
                logger.debug("[DATA_RECEIVED] tick for %s", message.get("symbol"))
            try:
                self.on_tick(message)
            except Exception:  # noqa: BLE001
                logger.exception("on_tick handler raised for message %r", message)

        def _on_error(message) -> None:
            logger.warning("[ERROR] FYERS WebSocket error: %s", message)

        def _on_close(message) -> None:
            # Distinguish an intentional stop (we already set _stop_event
            # before calling close_connection()) from an unexpected drop,
            # where the SDK's own restart_flag is still True and it will
            # attempt to reconnect on its own.
            if self._stop_event.is_set():
                logger.info("[STOPPED] FYERS WebSocket closed (intentional): %s", message)
            else:
                logger.warning("[RECONNECTING] FYERS WebSocket closed unexpectedly, SDK may attempt reconnect: %s", message)

        def _on_connect() -> None:
            logger.info("[CONNECTED] symbols=%s", self.symbols)
            socket.subscribe(symbols=self.symbols, data_type="SymbolUpdate")

        socket = data_ws.FyersDataSocket(
            access_token=access_token,
            log_path="",
            litemode=True,
            write_to_file=False,
            reconnect=True,
            on_connect=_on_connect,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close,
        )
        self._sdk_socket = socket
        socket.connect()

        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=1.0)
