"""Suggestion tracker (Phase B): observes genuine FYERS market data for open
TradeSuggestions and feeds it to the Phase A state engine. OFF unless
ENABLE_SUGGESTION_TRACKER=true, and never runs against mock FYERS data.

The tracker only observes, normalizes, orders and persists. Every lifecycle
decision (entry, targets, stop, invalidation, deadlines, same-bar policy,
gap pricing) is made by app/engines/suggestion_state_engine.py.

Evidence layers
  1. Candles (source of truth). Completed FYERS 5-minute candles are applied
     strictly after the persisted watermark `reconciled_through`, which
     starts at generated_at -- so a candle that began before generation (or
     that the engine rejects as pre-entry) is never used as post-generation
     evidence. Entry-day and later sessions both use 5m candles (one request
     per symbol covers the whole missed range); daily candles are fetched
     only for the official close when the engine needs one to expire a
     position. Nothing here lets a daily candle that spans the entry day
     decide a stop/target.
  2. Ticks (LiveDataHub, shared, reference counted). One subscription per
     open-suggestion symbol through the existing hub -- no extra WebSocket.
     Ticks are used for a COMMIT only to resolve a candle the engine marked
     ambiguous (stop and target in one bar), and only if the buffered ticks
     reproduce that candle's exact open/high/low/close with coverage that
     started before the bar -- i.e. the ticks demonstrably saw the extremes,
     so their order is real evidence. Otherwise the conservative stop-first
     candle result stands. The first tick after subscribing (a last-trade
     snapshot) and anything outside NSE hours are ignored. Tick times are
     RECEIPT times (FYERS lite mode carries no exchange timestamp).
  3. Batched quotes (fallback). When a symbol's ticks are stale during
     market hours, one batched /quotes request refreshes the live view.
Ticks and quotes also drive a PROVISIONAL live view (the engine applied to a
copy of the committed state) kept in memory/Redis -- never written as
events, never a stop/target.

Persistence: events and the watermark are committed atomically with the
state, immediately on any event. Non-event working values (MFE/MAE,
last observed price) are flushed every ~30s and on shutdown. A restart
reloads open suggestions, re-applies only candles after the watermark (the
engine is deterministic, so this is idempotent) and rebuilds subscriptions.

FYERS: every request goes through FyersClient at CRITICAL priority, i.e. the
shared Phase 0 limiter/metering/auth recovery/cache. If the session is not
CONNECTED, or a request raises FyersAuthRequiredError, tracking pauses:
nothing is inferred, subscriptions are released, rows are marked
AUTH_REQUIRED. After re-authentication candles are reconciled first, then
tick subscriptions resume.
"""

import asyncio
import collections
import dataclasses
import datetime as dt
from collections.abc import Callable
from typing import Protocol

from app.config import Settings, get_settings
from app.core.exceptions import FyersAuthRequiredError
from app.core.suggestion_constants import (
    OPEN_STATUSES,
    EvidenceMethod,
    ObservationSource,
    ScannerType,
    TrackingStatus,
)
from app.data.nse_holidays import LAST_VERIFIED_YEAR, is_nse_trading_day
from app.data.session_calendar import nth_nse_session_after
from app.engines import suggestion_state_engine as engine
from app.logging_config import get_logger
from app.services import suggestion_service as svc
from app.services.market_data_service import is_market_hours_ist

logger = get_logger(__name__)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SESSION_OPEN = dt.time(9, 15)
SESSION_CLOSE = dt.time(15, 30)
BAR = dt.timedelta(minutes=5)
PRICE_EPSILON = 1e-6
MAX_BUFFERED_TICKS_PER_SYMBOL = 100_000
LIVE_VIEW_TTL_SECONDS = 3600
CONNECTED = "CONNECTED"

# Process-level tracker states.
DISABLED = "DISABLED"
DISABLED_MOCK_MODE = "DISABLED_MOCK_MODE"
NOT_STARTED = "NOT_STARTED"
RUNNING = "RUNNING"
PAUSED_AUTH_REQUIRED = "PAUSED_AUTH_REQUIRED"
STOPPED = "STOPPED"


def live_view_key(suggestion_id: int) -> str:
    return f"mtf:suggestion_live:{suggestion_id}"


class TrackerDataError(RuntimeError):
    """Market data could not be fetched or failed validation. The affected
    suggestion is marked STALE and retried -- never skipped past."""


# ---- time helpers ------------------------------------------------------------------------


def _ist_date(ts: dt.datetime) -> dt.date:
    return ts.astimezone(IST).date()


# Returned in UTC: every stored timestamp is UTC (see suggestion_service._aware).
def session_open(d: dt.date) -> dt.datetime:
    return dt.datetime.combine(d, SESSION_OPEN, tzinfo=IST).astimezone(dt.UTC)


def session_end(d: dt.date) -> dt.datetime:
    return dt.datetime.combine(d, SESSION_CLOSE, tzinfo=IST).astimezone(dt.UTC)


def latest_expected_bar_end(now: dt.datetime, settle: dt.timedelta) -> dt.datetime:
    """The end of the most recent 5m bar that should be complete and
    settled at `now` (bars are aligned to 09:15 IST). Used only to decide
    whether a candle fetch can possibly return anything new."""
    t = now - settle
    d = _ist_date(t)
    for _ in range(15):
        if is_nse_trading_day(d):
            if t >= session_end(d):
                return session_end(d)
            if t >= session_open(d) + BAR:
                return session_open(d) + ((t - session_open(d)) // BAR) * BAR
        d -= dt.timedelta(days=1)
    return t


def session_complete(d: dt.date, now: dt.datetime, grace: dt.timedelta) -> bool:
    return now >= session_end(d) + grace


def _dates(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


# ---- market data layer -------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PriceObservation:
    symbol: str
    price: float
    at: dt.datetime
    source: str


class TrackerMarketData(Protocol):
    async def five_minute_bars(self, symbol: str, range_from: dt.date, range_to: dt.date) -> list[engine.Bar]: ...

    async def daily_close(self, symbol: str, session_date: dt.date) -> float | None: ...

    async def quotes(self, symbols: list[str]) -> dict[str, PriceObservation]: ...


def parse_candles(raw: dict, seconds: int, source: str) -> list[engine.Bar]:
    bars: dict[dt.datetime, engine.Bar] = {}
    for row in raw.get("candles") or []:
        try:
            ts, o, h, low, c = row[0], float(row[1]), float(row[2]), float(row[3]), float(row[4])
            start = dt.datetime.fromtimestamp(int(ts), tz=dt.UTC)
            bars[start] = engine.Bar(start=start, end=start + dt.timedelta(seconds=seconds),
                                     open=o, high=h, low=low, close=c, source=source)
        except (IndexError, TypeError, ValueError) as exc:
            raise TrackerDataError(f"malformed/inconsistent candle {row!r}: {exc}") from exc
    return [bars[k] for k in sorted(bars)]


class FyersTrackerMarketData:
    """Real FYERS adapter. Every call is a CRITICAL-priority FyersClient
    request (shared limiter, metering, 401 recovery, quote cache). Refuses
    mock mode: synthetic data must never produce a tracked outcome."""

    QUOTE_BATCH_SIZE = 50  # FYERS /quotes accepts up to 50 symbols per request
    MAX_INTRADAY_DAYS = 90  # FYERS caps minute resolutions at 100 days per request

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.request_counts: collections.Counter = collections.Counter()

    def _client(self):
        from app.integrations.fyers.fyers_client import FyersClient
        from app.integrations.fyers.request_control import RequestPriority

        if self.settings.use_mock_fyers:
            raise TrackerDataError("USE_MOCK_FYERS=true: the tracker never uses mock market data")
        return FyersClient(settings=self.settings, priority=RequestPriority.CRITICAL)

    async def five_minute_bars(self, symbol: str, range_from: dt.date, range_to: dt.date) -> list[engine.Bar]:
        from app.integrations.fyers.historical_data import get_intraday_history

        client = self._client()
        bars: list[engine.Bar] = []
        try:
            start = range_from
            while start <= range_to:
                end = min(range_to, start + dt.timedelta(days=self.MAX_INTRADAY_DAYS - 1))
                raw = await get_intraday_history(client, symbol, "5", start, end)
                self.request_counts["history_5m"] += 1
                bars.extend(parse_candles(raw, 300, ObservationSource.CANDLE_5M.value))
                start = end + dt.timedelta(days=1)
        finally:
            await client.aclose()
        return sorted({b.start: b for b in bars}.values(), key=lambda b: b.start)

    async def daily_close(self, symbol: str, session_date: dt.date) -> float | None:
        from app.integrations.fyers.historical_data import get_daily_history

        client = self._client()
        try:
            raw = await get_daily_history(client, symbol, session_date, session_date)
            self.request_counts["history_d"] += 1
        finally:
            await client.aclose()
        for row in raw.get("candles") or []:
            # Daily candle timestamps are the session date's midnight IST.
            if dt.datetime.fromtimestamp(int(row[0]), tz=dt.UTC).astimezone(IST).date() == session_date:
                return float(row[4])
        return None

    async def quotes(self, symbols: list[str]) -> dict[str, PriceObservation]:
        from app.integrations.fyers.quotes import get_quotes

        client = self._client()
        out: dict[str, PriceObservation] = {}
        try:
            for i in range(0, len(symbols), self.QUOTE_BATCH_SIZE):
                raw = await get_quotes(client, symbols[i:i + self.QUOTE_BATCH_SIZE])
                self.request_counts["quotes"] += 1
                # Verified live 2026-09-29: v.tt is the session-date stamp
                # (00:00 UTC, same for every symbol), NOT a last-trade time.
                # The observation is therefore stamped with the FETCH time --
                # adequate only because quotes feed the provisional view.
                fetched_at = dt.datetime.now(dt.UTC)
                for entry in raw.get("d") or []:
                    v = entry.get("v") or {}
                    name, lp = entry.get("n"), v.get("lp")
                    if entry.get("s") not in (None, "ok") or name is None or lp is None:
                        continue  # no usable last price -- left missing, never filled in
                    out[name] = PriceObservation(
                        symbol=name, price=float(lp), at=fetched_at, source=ObservationSource.QUOTE.value,
                    )
        finally:
            await client.aclose()
        return out


# ---- tracked working state -----------------------------------------------------------------


@dataclasses.dataclass
class TrackedSuggestion:
    id: int
    symbol: str
    scanner_type: str
    generated_at: dt.datetime
    max_holding_sessions: int | None
    state: engine.SuggestionState
    reconciled_through: dt.datetime
    last_sequence: int
    tracking_status: str
    tracking_status_reason: str | None = None
    dirty: bool = False
    pending_events: list[engine.EngineEvent] = dataclasses.field(default_factory=list)
    # provisional live view (never persisted as events)
    provisional: engine.SuggestionState | None = None
    provisional_events: list[str] = dataclasses.field(default_factory=list)
    live_price: float | None = None
    live_at: dt.datetime | None = None
    live_source: str | None = None
    live_dirty: bool = False
    # excursion timing (Phase D): bar-resolution "first observed by" times
    max_favorable_at: dt.datetime | None = None
    max_adverse_at: dt.datetime | None = None
    max_adverse_price_before_target_1: float | None = None

    def extra_columns(self) -> dict:
        return {"max_favorable_at": self.max_favorable_at, "max_adverse_at": self.max_adverse_at,
                "max_adverse_price_before_target_1": self.max_adverse_price_before_target_1}

    @property
    def is_open(self) -> bool:
        return self.state.status in OPEN_STATUSES

    def set_health(self, status: str, reason: str | None) -> None:
        if (status, reason) != (self.tracking_status, self.tracking_status_reason):
            self.tracking_status, self.tracking_status_reason = status, reason
            self.dirty = True


def _tracked_from_row(row, last_sequence: int) -> TrackedSuggestion:
    state = svc.state_from_row(row)
    watermark = svc._aware(row.reconciled_through) or state.generated_at
    return TrackedSuggestion(
        id=row.id, symbol=row.symbol, scanner_type=row.scanner_type, generated_at=state.generated_at,
        max_holding_sessions=row.max_holding_sessions, state=state,
        reconciled_through=max(watermark, state.generated_at), last_sequence=last_sequence,
        tracking_status=row.tracking_status or TrackingStatus.NOT_TRACKED.value,
        tracking_status_reason=row.tracking_status_reason,
        max_favorable_at=svc._aware(row.max_favorable_at), max_adverse_at=svc._aware(row.max_adverse_at),
        max_adverse_price_before_target_1=svc._f(row.max_adverse_price_before_target_1),
    )


def _annotate(events: list[engine.EngineEvent], evidence: dict) -> list[engine.EngineEvent]:
    return [dataclasses.replace(e, detail={**e.detail, "evidence": evidence}) for e in events]


def _bar_dict(bar: engine.Bar) -> dict:
    return {"start": bar.start.isoformat(), "end": bar.end.isoformat(), "open": bar.open, "high": bar.high,
            "low": bar.low, "close": bar.close, "source": bar.source}


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= PRICE_EPSILON


# ---- tracker -----------------------------------------------------------------------------------


class SuggestionTracker:
    def __init__(
        self,
        settings: Settings | None = None,
        session_factory: Callable | None = None,
        market_data: TrackerMarketData | None = None,
        hub=None,
        clock: Callable[[], dt.datetime] | None = None,
        auth_status: Callable[[], str] | None = None,
        redis_getter: Callable | None = None,
    ):
        self.settings = settings or get_settings()
        self._session_factory = session_factory
        self._market_data_injected = market_data is not None
        self.market_data: TrackerMarketData = market_data or FyersTrackerMarketData(self.settings)
        self._hub = hub
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))
        self._auth_status = auth_status
        self._redis_getter = redis_getter

        self.state = NOT_STARTED if self.settings.enable_suggestion_tracker else DISABLED
        self.tracked: dict[int, TrackedSuggestion] = {}
        self._subs: dict[str, str] = {}  # symbol -> LiveDataHub subscriber id
        self._consumers: dict[str, asyncio.Task] = {}
        self._ticks: dict[str, collections.deque] = {}
        self._coverage_since: dict[str, dt.datetime] = {}
        self._last_tick_at: dict[str, dt.datetime] = {}
        self._tasks: list[asyncio.Task] = []
        self._stop_event: asyncio.Event | None = None
        self._cycle_lock = asyncio.Lock()
        self.started_at: dt.datetime | None = None
        self.last_cycle_at: dt.datetime | None = None
        self.last_cycle: dict = {}
        self.metrics: collections.Counter = collections.Counter()

    # -- dependencies ---------------------------------------------------------------------------

    def _now(self) -> dt.datetime:
        return self._clock()

    def _session(self):
        if self._session_factory is None:
            from app.db.base import AsyncSessionLocal

            self._session_factory = AsyncSessionLocal
        return self._session_factory()

    @property
    def hub(self):
        if self._hub is None:
            from app.services.live_data_hub import live_data_hub

            self._hub = live_data_hub
        return self._hub

    def _auth_code(self) -> str:
        if self._auth_status is not None:
            return self._auth_status()
        from app.integrations.fyers.session import get_session_manager

        return get_session_manager(self.settings).status_code()

    def _redis(self):
        if self._redis_getter is not None:
            return self._redis_getter()
        from app.db.redis_client import get_redis

        return get_redis()

    @property
    def settle(self) -> dt.timedelta:
        return dt.timedelta(seconds=self.settings.suggestion_tracker_bar_settle_seconds)

    @property
    def grace(self) -> dt.timedelta:
        return dt.timedelta(minutes=self.settings.suggestion_tracker_session_close_grace_minutes)

    # -- lifecycle ------------------------------------------------------------------------------

    async def start(self) -> bool:
        if not self.settings.enable_suggestion_tracker:
            self.state = DISABLED
            logger.info("Suggestion tracker disabled (ENABLE_SUGGESTION_TRACKER=false)")
            return False
        if self.settings.use_mock_fyers and not self._market_data_injected:
            self.state = DISABLED_MOCK_MODE
            logger.warning("Suggestion tracker NOT started: USE_MOCK_FYERS=true (no outcomes from mock data)")
            return False
        if self._tasks:
            return True
        self._stop_event = asyncio.Event()
        self.started_at = self._now()
        self.state = RUNNING
        self._tasks = [
            asyncio.create_task(self._reconcile_loop(), name="suggestion-tracker-reconcile"),
            asyncio.create_task(self._flush_loop(), name="suggestion-tracker-flush"),
            asyncio.create_task(self._quote_loop(), name="suggestion-tracker-quotes"),
        ]
        logger.info("Suggestion tracker started")
        return True

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._tasks = []
        try:
            await self.flush()
        except Exception:  # noqa: BLE001
            logger.exception("Suggestion tracker: final flush failed")
        await self._release_all_subscriptions()
        if self.state not in (DISABLED, DISABLED_MOCK_MODE):
            self.state = STOPPED

    async def _sleep(self, seconds: float) -> bool:
        """True if stop was requested during the wait."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=max(1.0, seconds))
            return True
        except TimeoutError:
            return False

    def seconds_until_next_cycle(self, now: dt.datetime) -> float:
        if is_nse_trading_day(_ist_date(now)) and is_market_hours_ist(now):
            opened = session_open(_ist_date(now))
            next_boundary = opened + ((now - opened) // BAR + 1) * BAR
            # +2s margin: waking a few ms early (observed live 2026-09-29)
            # would leave the just-settled bar out of the cycle.
            return max(5.0, (next_boundary + self.settle - now).total_seconds() + 2.0)
        return float(self.settings.suggestion_tracker_idle_poll_seconds)

    async def _reconcile_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_cycle()
            except Exception:  # noqa: BLE001 -- one bad cycle must not kill tracking
                self.metrics["cycle_errors"] += 1
                logger.exception("Suggestion tracker cycle failed")
            if await self._sleep(self.seconds_until_next_cycle(self._now())):
                return

    async def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            if await self._sleep(self.settings.suggestion_tracker_flush_seconds):
                return
            try:
                await self.flush()
            except Exception:  # noqa: BLE001
                logger.exception("Suggestion tracker flush failed")

    async def _quote_loop(self) -> None:
        while not self._stop_event.is_set():
            if await self._sleep(self.settings.suggestion_tracker_quote_fallback_seconds):
                return
            try:
                await self.run_quote_fallback()
            except FyersAuthRequiredError as exc:
                await self._pause_for_auth(str(exc))
            except Exception:  # noqa: BLE001
                logger.exception("Suggestion tracker quote fallback failed")

    # -- reconciliation cycle ---------------------------------------------------------------------

    async def run_cycle(self) -> dict:
        async with self._cycle_lock:
            return await self._run_cycle()

    async def _run_cycle(self) -> dict:
        now = self._now()
        self.metrics["cycles"] += 1
        summary = {"at": now.isoformat(), "fetched_symbols": 0, "events": 0, "status": None}
        await self._sync_tracked()

        auth = self._auth_code()
        if auth != CONNECTED:
            await self._pause_for_auth(f"FYERS session status {auth}")
            summary["status"] = PAUSED_AUTH_REQUIRED
            return self._finish_cycle(now, summary)
        if self.state == PAUSED_AUTH_REQUIRED:
            logger.info("Suggestion tracker: FYERS session restored -- reconciling candles before resuming ticks")
        self.state = RUNNING

        horizon = latest_expected_bar_end(now, self.settle)
        by_symbol: dict[str, list[TrackedSuggestion]] = collections.defaultdict(list)
        for t in list(self.tracked.values()):
            if not t.is_open:
                continue
            if t.scanner_type != ScannerType.MTF.value:
                t.set_health(TrackingStatus.UNSUPPORTED.value, f"no approved tracking rules for {t.scanner_type}")
                continue
            by_symbol[t.symbol].append(t)

        try:
            for symbol, items in by_symbol.items():
                bars: list[engine.Bar] = []
                min_wm = min(t.reconciled_through for t in items)
                if min_wm < horizon:
                    try:
                        bars = await self.market_data.five_minute_bars(symbol, _ist_date(min_wm), _ist_date(now))
                        summary["fetched_symbols"] += 1
                    except FyersAuthRequiredError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        self.metrics["fetch_errors"] += 1
                        for t in items:
                            t.set_health(TrackingStatus.STALE.value, f"5m candles unavailable: {type(exc).__name__}")
                        continue
                for t in items:
                    before = len(t.pending_events)
                    try:
                        await self._reconcile(t, bars, now)
                    except TrackerDataError as exc:
                        t.set_health(TrackingStatus.STALE.value, str(exc)[:256])
                    summary["events"] += len(t.pending_events) - before
                    if t.pending_events:
                        await self._commit(t)
        except FyersAuthRequiredError as exc:
            await self._pause_for_auth(str(exc))
            summary["status"] = PAUSED_AUTH_REQUIRED
            return self._finish_cycle(now, summary)

        # Ticks resume only after candles covered everything up to now.
        await self._sync_subscriptions()
        self._prune_ticks()
        self._rebuild_provisional()
        summary["status"] = RUNNING
        return self._finish_cycle(now, summary)

    def _finish_cycle(self, now: dt.datetime, summary: dict) -> dict:
        summary["tracked_open"] = sum(1 for t in self.tracked.values() if t.is_open)
        self.last_cycle_at, self.last_cycle = now, summary
        return summary

    async def _reconcile(self, t: TrackedSuggestion, bars: list[engine.Bar], now: dt.datetime) -> None:
        cutoff = now - self.settle
        usable = [b for b in bars if b.start >= t.reconciled_through and b.end <= cutoff]
        by_date: dict[dt.date, list[engine.Bar]] = collections.defaultdict(list)
        for b in usable:
            by_date[_ist_date(b.start)].append(b)

        dates = sorted(set(by_date) | {
            d for d in _dates(_ist_date(t.reconciled_through), _ist_date(now)) if is_nse_trading_day(d)
        })
        watermark_before = t.reconciled_through
        gap = None
        for d in dates:
            watermark_at_day_start = t.reconciled_through
            for bar in by_date.get(d, []):
                self._apply(t, *self._evaluate_bar(t, bar), observed_by=bar.end)
                t.reconciled_through = max(t.reconciled_through, bar.end)
                if not t.is_open:
                    break
            if not t.is_open:
                break
            if not is_nse_trading_day(d) or not session_complete(d, now, self.grace):
                continue
            if not by_date.get(d) and watermark_at_day_start <= session_open(d):
                if d.year <= LAST_VERIFIED_YEAR:
                    # A verified NSE session with no candles at all: never
                    # skipped (skipping could hide a stop). Retried later.
                    gap = f"no 5m candles for verified NSE session {d.isoformat()}"
                    break
                # Beyond the verified holiday calendar this may be an unlisted
                # holiday; the suggestion already carries
                # session_calendar_verified=False. Not counted as a session.
                continue
            await self._close_session(t, d)
            t.reconciled_through = max(t.reconciled_through, session_end(d))
            if not t.is_open:
                break

        if gap:
            t.set_health(TrackingStatus.DATA_GAP.value, gap)
        else:
            t.set_health(TrackingStatus.TRACKING.value, None)
        if t.reconciled_through != watermark_before:
            t.dirty = True  # flushed within ~30s (immediately if events were produced)

    def _evaluate_bar(self, t: TrackedSuggestion, bar: engine.Bar):
        cand_state, cand_events = engine.apply_bar(t.state, bar)
        evidence = {"method": EvidenceMethod.CANDLE_RECONCILIATION.value, "bar": _bar_dict(bar)}
        if any(e.ambiguous_bar for e in cand_events):
            ticks = self._complete_ticks_for(t.symbol, bar)
            if ticks:
                state, tick_events = t.state, []
                for tick in ticks:
                    state, evs = engine.apply_tick(state, tick)
                    tick_events.extend(evs)
                if (state.entry_triggered_at is None) == (cand_state.entry_triggered_at is None):
                    self.metrics["ambiguity_resolved_by_ticks"] += 1
                    return state, _annotate(tick_events, {
                        "method": EvidenceMethod.ORDERED_TICKS.value, "resolved_candle_ambiguity": True,
                        "tick_count": len(ticks), "tick_time_basis": "RECEIVED_AT", "bar": _bar_dict(bar),
                    })
                evidence["tick_evidence_rejected"] = "ordered ticks disagree with the candle on entry"
            self.metrics["ambiguous_bars_conservative"] += 1
        return cand_state, _annotate(cand_events, evidence)

    def _apply(self, t: TrackedSuggestion, new_state: engine.SuggestionState, events: list[engine.EngineEvent],
               observed_by: dt.datetime | None = None) -> None:
        old = t.state
        if observed_by is not None:
            # Timing bookkeeping only (the engine owns the excursion values):
            # when a new extreme first appears, record the bar that showed it.
            if new_state.max_favorable_price is not None and new_state.max_favorable_price != old.max_favorable_price:
                t.max_favorable_at = observed_by
            if new_state.max_adverse_price is not None and new_state.max_adverse_price != old.max_adverse_price:
                t.max_adverse_at = observed_by
            if (any(e.event_type == "TARGET_1_HIT" for e in events) and old.entry_triggered_at is not None
                    and t.max_adverse_price_before_target_1 is None):
                t.max_adverse_price_before_target_1 = old.max_adverse_price
        if (
            t.state.entry_triggered_at is None and new_state.entry_triggered_at is not None
            and new_state.holding_deadline_session_date is None and t.max_holding_sessions
        ):
            # Same calendar function the service uses when it persists the
            # entry, so a multi-session catch-up can expire correctly.
            new_state.holding_deadline_session_date, _ = nth_nse_session_after(
                _ist_date(new_state.entry_triggered_at), t.max_holding_sessions
            )
        t.state = new_state
        t.pending_events.extend(events)
        t.dirty = True

    async def _close_session(self, t: TrackedSuggestion, d: dt.date) -> None:
        closed_at = session_end(d)
        try:
            state, events = engine.on_session_close(t.state, d, None, closed_at, ObservationSource.CANDLE_D.value)
        except ValueError:
            # The engine needs a real close to expire an open position.
            close = await self.market_data.daily_close(t.symbol, d)
            if close is None:
                raise TrackerDataError(f"official session close unavailable for {d.isoformat()}")
            state, events = engine.on_session_close(t.state, d, close, closed_at, ObservationSource.CANDLE_D.value)
        self._apply(t, state, _annotate(events, {
            "method": EvidenceMethod.SESSION_CLOSE.value, "session_date": d.isoformat(),
        }))

    # -- ticks -------------------------------------------------------------------------------------

    def _complete_ticks_for(self, symbol: str, bar: engine.Bar) -> list[engine.Tick] | None:
        coverage = self._coverage_since.get(symbol)
        buf = self._ticks.get(symbol)
        if coverage is None or coverage > bar.start or not buf:
            return None
        ticks = [tk for tk in buf if bar.start <= tk.at < bar.end]
        if not ticks:
            return None
        prices = [tk.price for tk in ticks]
        if (_same(prices[0], bar.open) and _same(prices[-1], bar.close)
                and _same(max(prices), bar.high) and _same(min(prices), bar.low)):
            return ticks
        return None

    def ingest_tick(self, symbol: str, raw: dict, first: bool = False) -> None:
        """One normalized LiveDataHub tick ({symbol, ltp, as_of})."""
        self.metrics["ticks_received"] += 1
        try:
            price = float(raw["ltp"])
            at = dt.datetime.fromisoformat(str(raw["as_of"]))
            at = at.replace(tzinfo=dt.UTC) if at.tzinfo is None else at.astimezone(dt.UTC)
        except (KeyError, TypeError, ValueError):
            self.metrics["ticks_ignored_malformed"] += 1
            return
        if first:
            # A fresh subscription is answered with the last trade, which may
            # predate this subscription (or generation): coverage starts here.
            self._coverage_since[symbol] = at
            self.metrics["ticks_ignored_subscribe_snapshot"] += 1
            return
        if not (is_nse_trading_day(_ist_date(at)) and is_market_hours_ist(at)):
            self.metrics["ticks_ignored_off_hours"] += 1
            return
        buf = self._ticks.setdefault(symbol, collections.deque(maxlen=MAX_BUFFERED_TICKS_PER_SYMBOL))
        buf.append(engine.Tick(at=at, price=price, source=ObservationSource.TICK.value))
        if len(buf) == buf.maxlen:
            self._coverage_since[symbol] = buf[0].at  # older ticks dropped: coverage shrinks
        self._last_tick_at[symbol] = at
        self.metrics["ticks_buffered"] += 1
        self._observe_provisional(symbol, buf[-1])

    async def _consume(self, symbol: str, queue: asyncio.Queue) -> None:
        first = True
        while True:
            raw = await queue.get()
            self.ingest_tick(symbol, raw, first=first)
            first = False

    def _prune_ticks(self) -> None:
        for symbol, buf in self._ticks.items():
            marks = [t.reconciled_through for t in self.tracked.values() if t.symbol == symbol and t.is_open]
            if not marks:
                buf.clear()
                continue
            floor = min(marks)
            while buf and buf[0].at < floor:
                buf.popleft()

    def _observe_provisional(self, symbol: str, obs: engine.Tick) -> None:
        for t in self.tracked.values():
            if t.symbol != symbol or not t.is_open:
                continue
            state, events = engine.apply_tick(t.provisional or t.state, obs)
            t.provisional = state
            t.provisional_events.extend(e.event_type for e in events)
            t.live_price, t.live_at, t.live_source, t.live_dirty = obs.price, obs.at, obs.source, True

    def _rebuild_provisional(self) -> None:
        for t in self.tracked.values():
            t.provisional, t.provisional_events = None, []
            for tick in self._ticks.get(t.symbol, ()):
                if tick.at >= t.reconciled_through and t.is_open:
                    state, events = engine.apply_tick(t.provisional or t.state, tick)
                    t.provisional = state
                    t.provisional_events.extend(e.event_type for e in events)

    # -- quote fallback --------------------------------------------------------------------------------

    async def run_quote_fallback(self) -> dict:
        now = self._now()
        if self.state != RUNNING or not (is_nse_trading_day(_ist_date(now)) and is_market_hours_ist(now)):
            return {"requested": []}
        stale_after = dt.timedelta(seconds=self.settings.live_data_stale_after_seconds)
        symbols = sorted({
            t.symbol for t in self.tracked.values()
            if t.is_open and t.scanner_type == ScannerType.MTF.value
            and (self._last_tick_at.get(t.symbol) is None or now - self._last_tick_at[t.symbol] > stale_after)
        })
        if not symbols:
            return {"requested": []}
        quotes = await self.market_data.quotes(symbols)
        self.metrics["quote_batches"] += 1
        for symbol, q in quotes.items():
            if is_nse_trading_day(_ist_date(q.at)) and is_market_hours_ist(q.at):
                self._observe_provisional(symbol, engine.Tick(at=q.at, price=q.price, source=q.source))
        return {"requested": symbols, "received": sorted(quotes)}

    # -- subscriptions ------------------------------------------------------------------------------------

    async def _sync_subscriptions(self) -> None:
        needed = set()
        if self.state == RUNNING:
            needed = {t.symbol for t in self.tracked.values() if t.is_open and t.scanner_type == ScannerType.MTF.value}
        for symbol in sorted(needed - set(self._subs)):
            try:
                sub_id, queue = self.hub.subscribe([symbol])
            except Exception as exc:  # noqa: BLE001 -- ticks are optional; candles remain authoritative
                logger.warning("Suggestion tracker: LiveDataHub subscribe failed for %s: %s", symbol, exc)
                continue
            self._subs[symbol] = sub_id
            self._consumers[symbol] = asyncio.create_task(self._consume(symbol, queue), name=f"tracker-ticks-{symbol}")
        for symbol in sorted(set(self._subs) - needed):
            await self._unsubscribe(symbol)

    async def _unsubscribe(self, symbol: str) -> None:
        sub_id = self._subs.pop(symbol, None)
        if sub_id is not None:
            self.hub.unsubscribe(sub_id, [symbol])  # decrements OUR reference only
        task = self._consumers.pop(symbol, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._ticks.pop(symbol, None)
        self._coverage_since.pop(symbol, None)
        self._last_tick_at.pop(symbol, None)

    async def _release_all_subscriptions(self) -> None:
        for symbol in list(self._subs):
            await self._unsubscribe(symbol)

    @property
    def subscribed_symbols(self) -> list[str]:
        return sorted(self._subs)

    # -- auth -----------------------------------------------------------------------------------------------

    async def _pause_for_auth(self, reason: str) -> None:
        if self.state != PAUSED_AUTH_REQUIRED:
            logger.warning("Suggestion tracker paused -- FYERS authentication required (%s)", reason)
        self.state = PAUSED_AUTH_REQUIRED
        self.metrics["auth_pauses"] += 1
        await self._release_all_subscriptions()
        changed = []
        for t in self.tracked.values():
            if t.is_open and t.tracking_status != TrackingStatus.AUTH_REQUIRED.value:
                t.tracking_status, t.tracking_status_reason = TrackingStatus.AUTH_REQUIRED.value, reason[:256]
                changed.append(t.id)
        if changed:
            async with self._session() as db:
                await svc.set_tracking_status(db, changed, TrackingStatus.AUTH_REQUIRED.value, reason)
            self.metrics["db_commits"] += 1

    # -- persistence -----------------------------------------------------------------------------------------

    async def _sync_tracked(self) -> None:
        async with self._session() as db:
            rows = await svc.load_open_suggestions(db)
            open_ids = {r.id for r in rows}
            for row in rows:
                if row.id not in self.tracked:
                    self.tracked[row.id] = _tracked_from_row(row, await svc.current_sequence(db, row.id))
        for sid in list(self.tracked):
            t = self.tracked[sid]
            if sid not in open_ids and not t.pending_events:
                del self.tracked[sid]  # closed elsewhere (e.g. cancelled) or already committed terminal

    async def _commit(self, t: TrackedSuggestion) -> bool:
        events = list(t.pending_events)
        async with self._session() as db:
            try:
                t.last_sequence = await svc.commit_tracking_update(
                    db, t.id, t.state, events, t.reconciled_through, t.tracking_status,
                    t.tracking_status_reason, t.last_sequence, extra=t.extra_columns(),
                )
            except svc.TrackingConflict:
                # Someone else changed the row: drop the working copy; the
                # next sync reloads it and re-reconciles from its watermark.
                self.metrics["commit_conflicts"] += 1
                self.tracked.pop(t.id, None)
                return False
        self.metrics["db_commits"] += 1
        self.metrics["events_committed"] += len(events)
        t.pending_events, t.dirty = [], False
        if not t.is_open:
            self.tracked.pop(t.id, None)
        return True

    async def flush(self) -> None:
        for t in list(self.tracked.values()):
            if t.dirty or t.pending_events:
                try:
                    await self._commit(t)
                except Exception:  # noqa: BLE001 -- kept dirty, retried next flush
                    self.metrics["commit_errors"] += 1
                    logger.exception("Suggestion tracker: commit failed for suggestion %s", t.id)
            if t.live_dirty:
                await self._write_live_view(t)

    async def _write_live_view(self, t: TrackedSuggestion) -> None:
        from app.services.cache_service import set_json

        p = t.provisional
        await set_json(self._redis(), live_view_key(t.id), {
            "suggestion_id": t.id,
            "symbol": t.symbol,
            "provisional": True,
            "note": "PROVISIONAL live view from ticks/quotes -- not committed evidence; "
                    "status/outcome change only through candle reconciliation.",
            "committed_status": t.state.status,
            "provisional_status": p.status if p else t.state.status,
            "provisional_events": t.provisional_events[-10:],
            "last_price": t.live_price,
            "last_price_at": t.live_at.isoformat() if t.live_at else None,
            "last_price_source": t.live_source,
            "provisional_max_favorable_excursion": p.max_favorable_excursion if p else None,
            "provisional_max_adverse_excursion": p.max_adverse_excursion if p else None,
            "written_at": self._now().isoformat(),
        }, LIVE_VIEW_TTL_SECONDS)
        t.live_dirty = False
        self.metrics["redis_live_view_writes"] += 1

    # -- diagnostics --------------------------------------------------------------------------------------------

    def status_snapshot(self) -> dict:
        now = self._now()
        uptime_min = (now - self.started_at).total_seconds() / 60 if self.started_at else None
        requests = dict(getattr(self.market_data, "request_counts", {}) or {})
        total_requests = sum(requests.values())
        return {
            "enabled": self.settings.enable_suggestion_tracker,
            "state": self.state,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_cycle_at": self.last_cycle_at.isoformat() if self.last_cycle_at else None,
            "last_cycle": self.last_cycle,
            "tracked_open": sum(1 for t in self.tracked.values() if t.is_open),
            "subscribed_symbols": self.subscribed_symbols,
            "fyers_requests": requests,
            "fyers_requests_per_minute": round(total_requests / uptime_min, 3) if uptime_min else None,
            "fyers_priority": "CRITICAL",
            "metrics": dict(self.metrics),
            "config": {
                "bar_resolution": "5m",
                "bar_settle_seconds": self.settings.suggestion_tracker_bar_settle_seconds,
                "session_close_grace_minutes": self.settings.suggestion_tracker_session_close_grace_minutes,
                "flush_seconds": self.settings.suggestion_tracker_flush_seconds,
                "quote_fallback_seconds": self.settings.suggestion_tracker_quote_fallback_seconds,
                "idle_poll_seconds": self.settings.suggestion_tracker_idle_poll_seconds,
            },
        }


_tracker: SuggestionTracker | None = None


def get_suggestion_tracker() -> SuggestionTracker:
    global _tracker
    if _tracker is None:
        _tracker = SuggestionTracker()
    return _tracker

