"""Phase B: suggestion tracker. Controlled suggestions are created through
the internal service (never an API), market data comes from an injected fake
or an httpx.MockTransport -- no test touches the real FYERS session/token.
SQLite in-memory DB, isolated Redis DB 15 (conftest)."""

import asyncio
import collections
import datetime as dt
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.core.exceptions import FyersAuthRequiredError
from app.core.suggestion_constants import (
    LevelQuality,
    ObservedPriceBasis,
    SuggestionEventType as E,
    SuggestionOutcome as O,
    SuggestionStatus as S,
    TrackingStatus,
)
from app.db.base import Base
from app.engines.suggestion_state_engine import Bar
from app.models.trade_suggestion import TradeSuggestion
from app.models.trade_suggestion_event import TradeSuggestionEvent
from app.schemas.suggestion import LevelInput, SuggestionCreateRequest
from app.services import suggestion_service as svc
from app.services import suggestion_tracker_service as trk
from app.services.suggestion_tracker_service import (
    DISABLED,
    DISABLED_MOCK_MODE,
    PAUSED_AUTH_REQUIRED,
    RUNNING,
    FyersTrackerMarketData,
    PriceObservation,
    SuggestionTracker,
    TrackerDataError,
)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MON = dt.date(2026, 9, 28)  # Mon; Oct 2 is an NSE holiday
TUE, WED, THU = dt.date(2026, 9, 29), dt.date(2026, 9, 30), dt.date(2026, 10, 1)
SYM = "NSE:TEST-EQ"
V = LevelQuality.VERIFIED_STRUCTURE.value


def ist(d: dt.date, hh: int, mm: int, ss: int = 0) -> dt.datetime:
    return dt.datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=IST).astimezone(dt.UTC)


def bar(d, hh, mm, o, h, low, c) -> Bar:
    start = ist(d, hh, mm)
    return Bar(start=start, end=start + dt.timedelta(minutes=5), open=o, high=h, low=low, close=c, source="CANDLE_5M")


def request(symbol=SYM, generated_at=None, **overrides) -> SuggestionCreateRequest:
    levels = {
        "entry_low": LevelInput(price=100.0, quality=V, provenance="support"),
        "entry_high": LevelInput(price=102.0, quality=V, provenance="support band"),
        "target_1": LevelInput(price=110.0, quality=V, provenance="20D high"),
        "target_2": LevelInput(price=120.0, quality=V, provenance="measured move"),
        "stop_loss": LevelInput(price=95.0, quality=V, provenance="swing low"),
    }
    base = dict(
        scanner_type="MTF", market="NSE_EQ", symbol=symbol, instrument_type="EQUITY", direction="LONG",
        setup_type="PULLBACK", generated_at=generated_at or ist(MON, 10, 0), generation_market_price=101.0,
        generation_price_source="QUOTE", market_status="MARKET_OPEN_LIVE", data_quality="HIGH", levels=levels,
        evidence_snapshot={"rsi_14": 55.0},
    )
    base.update(overrides)
    return SuggestionCreateRequest(**base)


# ---- fakes -------------------------------------------------------------------------------------


class Clock:
    def __init__(self, now: dt.datetime):
        self.now = now

    def __call__(self) -> dt.datetime:
        return self.now


class FakeMarketData:
    def __init__(self, log: list | None = None):
        self.bars: dict[str, list[Bar]] = collections.defaultdict(list)
        self.closes: dict[tuple[str, dt.date], float] = {}
        self.quote_prices: dict[str, PriceObservation] = {}
        self.calls: list[tuple] = []
        self.log = log if log is not None else []
        self.raise_auth = False
        self.raise_error: Exception | None = None

    async def five_minute_bars(self, symbol, range_from, range_to):
        self.calls.append(("bars", symbol, range_from, range_to))
        self.log.append(("fetch", symbol))
        if self.raise_auth:
            raise FyersAuthRequiredError("FYERS session expired (HTTP 401 on /history)", status_code=401)
        if self.raise_error:
            raise self.raise_error
        return [b for b in self.bars[symbol] if range_from <= b.start.astimezone(IST).date() <= range_to]

    async def daily_close(self, symbol, session_date):
        self.calls.append(("daily", symbol, session_date))
        return self.closes.get((symbol, session_date))

    async def quotes(self, symbols):
        self.calls.append(("quotes", tuple(symbols)))
        return {s: q for s, q in self.quote_prices.items() if s in symbols}


class FakeHub:
    def __init__(self, log: list | None = None):
        self.refs: collections.Counter = collections.Counter()
        self.log = log if log is not None else []

    def subscribe(self, symbols):
        for s in symbols:
            self.refs[s] += 1
        self.log.append(("subscribe", tuple(symbols)))
        return uuid.uuid4().hex, asyncio.Queue()

    def unsubscribe(self, sub_id, symbols):
        for s in symbols:
            self.refs[s] -= 1
            if self.refs[s] <= 0:
                del self.refs[s]
        self.log.append(("unsubscribe", tuple(symbols)))


# ---- fixtures ---------------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def factory():
    import app.main  # noqa: F401 -- registers every model on Base.metadata

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


@pytest_asyncio.fixture
async def make_tracker(factory):
    created: list[SuggestionTracker] = []

    def _make(md=None, hub=None, clock=None, auth=None, **settings_overrides) -> SuggestionTracker:
        settings = Settings(enable_suggestion_tracker=True, use_mock_fyers=True, **settings_overrides)
        auth_holder = auth if auth is not None else ["CONNECTED"]
        tracker = SuggestionTracker(
            settings=settings, session_factory=factory, market_data=md or FakeMarketData(), hub=hub or FakeHub(),
            clock=clock or Clock(ist(MON, 10, 16, 30)), auth_status=lambda: auth_holder[0],
        )
        created.append(tracker)
        return tracker

    yield _make
    for tracker in created:
        await tracker._release_all_subscriptions()


async def create(factory, **kwargs) -> int:
    settings = kwargs.pop("settings", None)
    async with factory() as db:
        result = await svc.create_suggestion(db, request(**kwargs), settings)
    assert result.suggestion_id is not None, result
    return result.suggestion_id


async def load(factory, sid: int) -> tuple[TradeSuggestion, list[TradeSuggestionEvent]]:
    async with factory() as db:
        row = await db.get(TradeSuggestion, sid)
        return row, await svc.list_events(db, sid)


def types(events) -> list[str]:
    return [e.event_type for e in events]


def transitions(events) -> list[str]:
    """Status-changing events only (drops study-only BREAKEVEN_REVISITED...)."""
    return [e.event_type for e in events if e.from_status != e.to_status]


# ---- startup / idle -------------------------------------------------------------------------------------


async def test_tracker_is_disabled_by_default():
    assert Settings.model_fields["enable_suggestion_tracker"].default is False
    assert Settings().enable_suggestion_tracker is False
    tracker = SuggestionTracker(settings=Settings())
    assert await tracker.start() is False
    assert tracker.state == DISABLED and tracker._tasks == []
    await tracker.stop()  # safe no-op


async def test_tracker_refuses_mock_fyers_data():
    tracker = SuggestionTracker(settings=Settings(enable_suggestion_tracker=True, use_mock_fyers=True))
    assert await tracker.start() is False
    assert tracker.state == DISABLED_MOCK_MODE
    with pytest.raises(TrackerDataError):
        FyersTrackerMarketData(Settings(use_mock_fyers=True))._client()


async def test_enabled_tracker_starts_and_stops_cleanly(make_tracker):
    tracker = make_tracker()
    assert await tracker.start() is True
    assert tracker.state == RUNNING and len(tracker._tasks) == 3
    await asyncio.sleep(0.05)
    await tracker.stop()
    assert tracker._tasks == [] and tracker.state == "STOPPED"


async def test_idle_tracker_makes_no_fyers_requests(make_tracker):
    md, hub = FakeMarketData(), FakeHub()
    tracker = make_tracker(md=md, hub=hub)
    summary = await tracker.run_cycle()
    assert summary["status"] == RUNNING and summary["fetched_symbols"] == 0
    assert (await tracker.run_quote_fallback())["requested"] == []
    assert md.calls == [] and hub.log == []


# ---- WAITING_ENTRY ----------------------------------------------------------------------------------------


async def test_fresh_touch_after_generation_triggers_entry(factory, make_tracker):
    sid = await create(factory, generated_at=ist(MON, 10, 2))
    md = FakeMarketData()
    md.bars[SYM] = [
        bar(MON, 10, 0, 101, 101.5, 100.5, 101),  # in zone but started BEFORE generation
        bar(MON, 10, 5, 103, 104, 102.5, 103.5),  # above the zone
        bar(MON, 10, 10, 103, 103.2, 101.5, 102.8),  # comes back into the zone
    ]
    tracker = make_tracker(md=md, clock=Clock(ist(MON, 10, 16, 30)))
    await tracker.run_cycle()

    row, events = await load(factory, sid)
    assert row.status == S.ACTIVE
    assert types(events) == [E.SUGGESTION_CREATED, E.ENTRY_TRIGGERED]
    entry = events[1]
    assert entry.observed_at.replace(tzinfo=dt.UTC) == ist(MON, 10, 15)
    assert float(entry.observed_market_price) == 102.0 and entry.observed_price_basis == ObservedPriceBasis.WITHIN_BAR_RANGE
    assert entry.data_source == "CANDLE_5M"
    assert entry.detail["evidence"]["method"] == "CANDLE_RECONCILIATION"
    assert entry.detail["entry_low"] == 100.0 and entry.detail["entry_high"] == 102.0
    assert row.reconciled_through.replace(tzinfo=dt.UTC) == ist(MON, 10, 15)
    assert row.tracking_status == TrackingStatus.TRACKING
    assert float(row.generation_market_price) == 101.0  # generation evidence untouched
    assert md.calls[0] == ("bars", SYM, MON, MON)


async def test_pre_generation_candle_never_triggers_entry(factory, make_tracker):
    sid = await create(factory, generated_at=ist(MON, 10, 2))
    md = FakeMarketData()
    md.bars[SYM] = [bar(MON, 10, 0, 101, 101.5, 100.5, 101)]  # the only in-zone candle predates generation
    tracker = make_tracker(md=md, clock=Clock(ist(MON, 10, 16, 30)))
    await tracker.run_cycle()
    row, events = await load(factory, sid)
    assert row.status == S.WAITING_ENTRY and types(events) == [E.SUGGESTION_CREATED]


async def test_stop_before_entry_is_invalidation_not_a_loss(factory, make_tracker):
    sid = await create(factory)
    md = FakeMarketData()
    md.bars[SYM] = [bar(MON, 10, 5, 99, 99.5, 94, 96)]  # below zone, through the stop, never in the zone
    tracker = make_tracker(md=md)
    await tracker.run_cycle()
    row, events = await load(factory, sid)
    assert row.status == S.INVALIDATED and row.outcome == O.INVALIDATED_BEFORE_ENTRY
    assert row.entry_triggered_at is None and types(events)[-1] == E.INVALIDATED
    assert row.open_dedup_key is None


async def test_entry_window_expiry_produces_no_entry(factory, make_tracker):
    sid = await create(factory)  # generated Mon 10:00 IST -> entry deadline Tue Oct 6
    md = FakeMarketData()
    days = [MON, TUE, WED, THU, dt.date(2026, 10, 5), dt.date(2026, 10, 6)]
    md.bars[SYM] = [bar(d, 11, 0, 105, 106, 104, 105) for d in days]  # always above the zone
    tracker = make_tracker(md=md, clock=Clock(ist(dt.date(2026, 10, 6), 16, 0)))
    await tracker.run_cycle()

    row, events = await load(factory, sid)
    assert row.status == S.NO_ENTRY and row.outcome == O.NO_ENTRY
    assert types(events) == [E.SUGGESTION_CREATED, E.NO_ENTRY]
    assert events[-1].observed_at.replace(tzinfo=dt.UTC) == ist(dt.date(2026, 10, 6), 15, 30)
    assert events[-1].detail["evidence"]["method"] == "SESSION_CLOSE"
    assert not any(c[0] == "daily" for c in md.calls)  # no close price needed for NO_ENTRY
    assert len([c for c in md.calls if c[0] == "bars"]) == 1  # one request covered all missed sessions


# ---- in position ------------------------------------------------------------------------------------------


ENTRY_BAR = bar(MON, 10, 5, 101.5, 102, 101, 101.8)  # opens inside the zone -> entry at 101.5


async def _active(factory, make_tracker, later_bars, clock_at, **kw):
    sid = await create(factory)
    md = FakeMarketData()
    md.bars[SYM] = [ENTRY_BAR, *later_bars]
    tracker = make_tracker(md=md, clock=Clock(clock_at), **kw)
    await tracker.run_cycle()
    return sid, tracker, md


async def test_active_to_target_1_to_target_2(factory, make_tracker):
    sid, _, _ = await _active(factory, make_tracker, [
        bar(MON, 10, 10, 102, 110.5, 101.8, 110), bar(MON, 10, 15, 110, 121, 109, 120.5),
    ], ist(MON, 10, 21, 30))
    row, events = await load(factory, sid)
    assert types(events) == [E.SUGGESTION_CREATED, E.ENTRY_TRIGGERED, E.TARGET_1_HIT, E.TARGET_2_HIT]
    assert row.status == S.TARGET_2_HIT and row.outcome == O.SUCCESS_TARGET_2
    t1, t2 = events[2], events[3]
    assert float(t1.threshold_price) == 110.0 and t1.observed_price_basis == ObservedPriceBasis.WITHIN_BAR_RANGE
    assert float(t2.threshold_price) == 120.0
    assert (t1.from_status, t1.to_status) == (S.ACTIVE, S.TARGET_1_HIT)
    assert (t2.from_status, t2.to_status) == (S.TARGET_1_HIT, S.TARGET_2_HIT)
    assert float(row.stop_loss) == 95.0 and float(row.target_1) == 110.0  # original levels untouched


async def test_active_to_stop_is_failed_stop(factory, make_tracker):
    sid, _, _ = await _active(factory, make_tracker, [bar(MON, 10, 10, 101, 101.2, 94.5, 95.5)], ist(MON, 10, 16, 30))
    row, events = await load(factory, sid)
    assert row.status == S.STOP_HIT and row.outcome == O.FAILED_STOP
    assert float(events[-1].threshold_price) == 95.0 and row.ambiguous_bar is False


async def test_target_1_then_stop_is_partial_success(factory, make_tracker):
    sid, _, _ = await _active(factory, make_tracker, [
        bar(MON, 10, 10, 102, 111, 101.8, 109), bar(MON, 10, 15, 108, 108.5, 94, 95),
    ], ist(MON, 10, 21, 30))
    row, events = await load(factory, sid)
    assert transitions(events)[-2:] == [E.TARGET_1_HIT, E.STOP_HIT]
    assert E.BREAKEVEN_REVISITED_AFTER_TARGET_1 in types(events)  # study data only, stop unchanged
    assert row.outcome == O.PARTIAL_SUCCESS  # not reinterpreted as a failure
    assert events[-1].from_status == S.TARGET_1_HIT
    assert float(row.stop_loss) == 95.0  # stop never moved to breakeven


AMBIGUOUS_BAR = bar(MON, 10, 10, 103, 111, 94, 96)  # touches target 1 AND the stop


async def test_same_bar_ambiguity_is_conservative_stop_first(factory, make_tracker):
    sid, tracker, _ = await _active(factory, make_tracker, [AMBIGUOUS_BAR], ist(MON, 10, 16, 30))
    row, events = await load(factory, sid)
    assert row.status == S.STOP_HIT and row.outcome == O.FAILED_STOP
    assert row.ambiguous_bar is True and events[-1].ambiguous_bar is True
    assert events[-1].detail["target_1_touched_in_bar"] is True
    assert tracker.metrics["ambiguous_bars_conservative"] == 1


async def _feed_ticks(tracker, symbol, snapshot_at, ticks):
    tracker.ingest_tick(symbol, {"ltp": 102.0, "as_of": snapshot_at.isoformat()}, first=True)
    for at, price in ticks:
        tracker.ingest_tick(symbol, {"ltp": price, "as_of": at.isoformat()})


async def test_ordered_ticks_resolve_same_bar_ambiguity(factory, make_tracker):
    sid = await create(factory)
    md = FakeMarketData()
    md.bars[SYM] = [ENTRY_BAR]
    clock = Clock(ist(MON, 10, 11, 30))
    tracker = make_tracker(md=md, clock=clock)
    await tracker.run_cycle()  # entry committed; symbol subscribed
    assert tracker.subscribed_symbols == [SYM]

    await _feed_ticks(tracker, SYM, ist(MON, 10, 9, 59), [
        (ist(MON, 10, 10, 1), 103.0), (ist(MON, 10, 11), 111.0), (ist(MON, 10, 12), 108.0),
        (ist(MON, 10, 13), 94.0), (ist(MON, 10, 14, 30), 96.0),
    ])
    md.bars[SYM].append(AMBIGUOUS_BAR)
    clock.now = ist(MON, 10, 16, 30)
    await tracker.run_cycle()

    row, events = await load(factory, sid)
    moves = [e for e in events if e.from_status != e.to_status][-2:]
    assert [e.event_type for e in moves] == [E.TARGET_1_HIT, E.STOP_HIT]
    assert row.outcome == O.PARTIAL_SUCCESS and row.ambiguous_bar is False
    assert {e.data_source for e in moves} == {"TICK"}
    assert moves[-1].detail["evidence"]["method"] == "ORDERED_TICKS"
    assert moves[-1].detail["evidence"]["tick_time_basis"] == "RECEIVED_AT"
    assert float(moves[0].observed_market_price) == 111.0 and float(moves[1].observed_market_price) == 94.0
    assert moves[0].observed_at < moves[1].observed_at  # the order the ticks proved


async def test_incomplete_ticks_do_not_override_the_conservative_candle(factory, make_tracker):
    sid = await create(factory)
    md = FakeMarketData()
    md.bars[SYM] = [ENTRY_BAR]
    clock = Clock(ist(MON, 10, 11, 30))
    tracker = make_tracker(md=md, clock=clock)
    await tracker.run_cycle()
    # Ticks never saw the 94 low: they cannot prove the order.
    await _feed_ticks(tracker, SYM, ist(MON, 10, 9, 59), [
        (ist(MON, 10, 10, 1), 103.0), (ist(MON, 10, 11), 111.0), (ist(MON, 10, 14, 30), 96.0),
    ])
    md.bars[SYM].append(AMBIGUOUS_BAR)
    clock.now = ist(MON, 10, 16, 30)
    await tracker.run_cycle()
    row, _ = await load(factory, sid)
    assert row.outcome == O.FAILED_STOP and row.ambiguous_bar is True


async def test_gap_through_target_records_threshold_and_observed_separately(factory, make_tracker):
    sid, _, _ = await _active(factory, make_tracker, [bar(TUE, 9, 15, 113, 114, 112, 113.5)], ist(TUE, 9, 21, 30))
    _, events = await load(factory, sid)
    t1 = events[-1]
    assert t1.event_type == E.TARGET_1_HIT
    assert float(t1.threshold_price) == 110.0 and float(t1.observed_market_price) == 113.0
    assert t1.observed_price_basis == ObservedPriceBasis.GAP_OPEN


async def test_gap_through_stop_records_threshold_and_observed_separately(factory, make_tracker):
    sid, _, _ = await _active(factory, make_tracker, [bar(TUE, 9, 15, 93, 94, 92, 93.5)], ist(TUE, 9, 21, 30))
    row, events = await load(factory, sid)
    stop = events[-1]
    assert stop.event_type == E.STOP_HIT and row.outcome == O.FAILED_STOP
    assert float(stop.threshold_price) == 95.0 and float(stop.observed_market_price) == 93.0
    assert stop.observed_price_basis == ObservedPriceBasis.GAP_OPEN
    assert float(row.stop_hit_price) == 93.0


async def test_mfe_mae_are_tracked_and_flushed_not_written_per_observation(factory, make_tracker):
    sid, tracker, md = await _active(factory, make_tracker, [], ist(MON, 10, 11, 30))  # entry committed
    md.bars[SYM].append(bar(MON, 10, 10, 102, 108, 99, 107))
    tracker._clock.now = ist(MON, 10, 16, 30)
    await tracker.run_cycle()  # no event -> working state only
    working = tracker.tracked[sid].state
    assert working.max_favorable_excursion == pytest.approx(6.4039, abs=1e-4)  # (108-101.5)/101.5
    assert working.max_adverse_excursion == pytest.approx(-2.4631, abs=1e-4)  # (99-101.5)/101.5

    row, _ = await load(factory, sid)
    assert float(row.max_favorable_price) == 102.0  # not yet written
    commits_before = tracker.metrics["db_commits"]
    await tracker.flush()
    assert tracker.metrics["db_commits"] == commits_before + 1
    row, _ = await load(factory, sid)
    assert float(row.max_favorable_price) == 108.0 and float(row.max_adverse_price) == 99.0
    assert float(row.max_favorable_excursion) == pytest.approx(6.4039, abs=1e-4)
    assert float(row.max_adverse_excursion) == pytest.approx(-2.4631, abs=1e-4)


async def test_excursion_timing_and_adverse_before_target_1_are_recorded(factory, make_tracker):
    sid, tracker, _ = await _active(factory, make_tracker, [
        bar(MON, 10, 10, 102, 104, 99.5, 103),  # new high + new low
        bar(MON, 10, 15, 103, 103.5, 101, 103),  # nothing new
        bar(MON, 10, 20, 103, 110.5, 102.5, 110),  # target 1
    ], ist(MON, 10, 26, 30))
    await tracker.flush()
    row, _ = await load(factory, sid)
    assert row.max_favorable_at.replace(tzinfo=dt.UTC) == ist(MON, 10, 25)  # the T1 bar made the new high
    assert row.max_adverse_at.replace(tzinfo=dt.UTC) == ist(MON, 10, 15)  # 99.5 first seen by the 10:10 bar's end
    assert float(row.max_adverse_price_before_target_1) == 99.5  # through the bar BEFORE the T1 bar


async def test_extra_columns_are_restricted_to_tracker_owned_fields(factory):
    sid = await create(factory)
    async with factory() as db:
        row = await db.get(TradeSuggestion, sid)
        with pytest.raises(ValueError):
            await svc.commit_tracking_update(db, sid, svc.state_from_row(row), [], None, "TRACKING", None, 1,
                                             extra={"stop_loss": 1.0})


async def test_expiry_uses_the_official_daily_close(factory, make_tracker):
    s = Settings(suggestion_mtf_max_holding_sessions=2)
    sid = await create(factory, settings=s)  # entry Mon -> holding deadline Wed
    md = FakeMarketData()
    md.bars[SYM] = [ENTRY_BAR, bar(TUE, 11, 0, 104, 105, 103, 104), bar(WED, 11, 0, 104, 106, 103, 105)]
    md.closes[(SYM, WED)] = 105.5
    tracker = make_tracker(md=md, clock=Clock(ist(WED, 16, 0)))
    await tracker.run_cycle()
    row, events = await load(factory, sid)
    assert row.status == S.EXPIRED and row.outcome == O.EXPIRED
    assert float(row.close_price) == 105.5 and events[-1].data_source == "CANDLE_D"
    assert ("daily", SYM, WED) in md.calls


async def test_missing_official_close_never_expires(factory, make_tracker):
    s = Settings(suggestion_mtf_max_holding_sessions=2)
    sid = await create(factory, settings=s)
    md = FakeMarketData()
    md.bars[SYM] = [ENTRY_BAR, bar(TUE, 11, 0, 104, 105, 103, 104), bar(WED, 11, 0, 104, 106, 103, 105)]
    tracker = make_tracker(md=md, clock=Clock(ist(WED, 16, 0)))
    await tracker.run_cycle()
    await tracker.flush()
    row, _ = await load(factory, sid)
    assert row.status == S.ACTIVE and row.tracking_status == TrackingStatus.STALE
    assert "close unavailable" in row.tracking_status_reason


async def test_verified_session_without_candles_is_a_data_gap_not_skipped(factory, make_tracker):
    sid, tracker, _ = await _active(factory, make_tracker, [bar(WED, 10, 0, 100, 100.5, 94, 95)], ist(WED, 16, 0))
    await tracker.flush()
    row, events = await load(factory, sid)
    assert row.status == S.ACTIVE  # Wednesday's stop is NOT applied past the Tuesday gap
    assert row.tracking_status == TrackingStatus.DATA_GAP and "2026-09-29" in row.tracking_status_reason
    assert types(events) == [E.SUGGESTION_CREATED, E.ENTRY_TRIGGERED]


async def test_holding_deadline_beyond_verified_calendar_is_flagged(factory, make_tracker):
    d = dt.date(2026, 12, 3)
    sid = await create(factory, generated_at=ist(d, 10, 0))
    row, _ = await load(factory, sid)
    assert row.session_calendar_verified is True  # entry deadline Dec 10 is inside 2026
    md = FakeMarketData()
    md.bars[SYM] = [bar(d, 10, 5, 101.5, 102, 101, 101.8)]
    tracker = make_tracker(md=md, clock=Clock(ist(d, 10, 11, 30)))
    await tracker.run_cycle()
    row, _ = await load(factory, sid)
    assert row.holding_deadline_session_date.year == 2027
    assert row.session_calendar_verified is False


async def test_fetch_failure_marks_stale_without_changing_lifecycle(factory, make_tracker):
    sid = await create(factory)
    md = FakeMarketData()
    md.raise_error = TrackerDataError("malformed candle")
    tracker = make_tracker(md=md)
    await tracker.run_cycle()
    await tracker.flush()
    row, events = await load(factory, sid)
    assert row.status == S.WAITING_ENTRY and row.tracking_status == TrackingStatus.STALE
    assert types(events) == [E.SUGGESTION_CREATED]


# ---- idempotency / restart ----------------------------------------------------------------------------------


async def test_repeated_cycles_never_duplicate_events(factory, make_tracker):
    sid, tracker, _ = await _active(factory, make_tracker, [bar(MON, 10, 10, 102, 110.5, 101.8, 110)], ist(MON, 10, 16, 30))
    await tracker.run_cycle()
    await tracker.run_cycle()
    await tracker.flush()
    _, events = await load(factory, sid)
    assert types(events) == [E.SUGGESTION_CREATED, E.ENTRY_TRIGGERED, E.TARGET_1_HIT]
    assert [e.sequence for e in events] == [1, 2, 3]


async def test_restart_recovery_resumes_from_the_watermark(factory, make_tracker):
    sid = await create(factory)
    md = FakeMarketData()
    md.bars[SYM] = [ENTRY_BAR, bar(MON, 10, 10, 102, 104, 101.9, 103)]
    first = make_tracker(md=md, clock=Clock(ist(MON, 10, 16, 30)))
    await first.run_cycle()
    await first.stop()  # graceful shutdown flushes working state
    row, _ = await load(factory, sid)
    assert row.reconciled_through.replace(tzinfo=dt.UTC) == ist(MON, 10, 15)

    md.bars[SYM].append(bar(TUE, 10, 0, 105, 110.5, 104, 110))
    hub = FakeHub()
    second = make_tracker(md=md, hub=hub, clock=Clock(ist(TUE, 10, 6, 30)))
    await second.run_cycle()

    row, events = await load(factory, sid)
    assert types(events) == [E.SUGGESTION_CREATED, E.ENTRY_TRIGGERED, E.TARGET_1_HIT]
    assert [e.sequence for e in events] == [1, 2, 3]
    assert hub.refs[SYM] == 1  # subscription rebuilt after restart
    assert float(row.max_favorable_price) == 110.5


async def test_crash_before_flush_is_recovered_deterministically(factory, make_tracker):
    sid = await create(factory)
    md = FakeMarketData()
    md.bars[SYM] = [ENTRY_BAR, bar(MON, 10, 10, 102, 107, 100.5, 106)]
    crashed = make_tracker(md=md, clock=Clock(ist(MON, 10, 16, 30)))
    await crashed.run_cycle()  # entry committed; the 10:10 bar only in memory (no flush -> "crash")
    in_memory_mfe = crashed.tracked[sid].state.max_favorable_excursion

    recovered = make_tracker(md=md, clock=Clock(ist(MON, 10, 16, 30)))
    await recovered.run_cycle()
    await recovered.flush()
    row, events = await load(factory, sid)
    assert types(events) == [E.SUGGESTION_CREATED, E.ENTRY_TRIGGERED]
    assert float(row.max_favorable_excursion) == pytest.approx(in_memory_mfe)


async def test_concurrent_external_change_is_not_overwritten(factory, make_tracker):
    sid, tracker, md = await _active(factory, make_tracker, [], ist(MON, 10, 11, 30))
    md.bars[SYM].append(bar(MON, 10, 10, 102, 104, 101.9, 103))
    tracker._clock.now = ist(MON, 10, 16, 30)
    await tracker.run_cycle()  # working state now dirty
    assert tracker.tracked[sid].dirty
    async with factory() as db:
        await svc.cancel_suggestion(db, sid, "operator review")
    await tracker.flush()  # stale working copy must not clobber the cancellation
    row, events = await load(factory, sid)
    assert row.status == S.CANCELLED and types(events)[-1] == E.CANCELLED
    assert tracker.metrics["commit_conflicts"] == 1 and sid not in tracker.tracked


# ---- authentication --------------------------------------------------------------------------------------------


async def test_auth_expiry_pauses_without_inferring_outcomes(factory, make_tracker):
    sid = await create(factory)
    md, hub, auth = FakeMarketData(), FakeHub(), ["REFRESH_REQUIRED"]
    md.bars[SYM] = [bar(MON, 10, 5, 99, 99.5, 94, 96)]  # would invalidate -- must not be inferred
    tracker = make_tracker(md=md, hub=hub, auth=auth)
    summary = await tracker.run_cycle()

    assert summary["status"] == PAUSED_AUTH_REQUIRED and tracker.state == PAUSED_AUTH_REQUIRED
    assert md.calls == [] and hub.refs == {}
    row, events = await load(factory, sid)
    assert row.status == S.WAITING_ENTRY and row.outcome == O.PENDING
    assert row.tracking_status == TrackingStatus.AUTH_REQUIRED
    assert types(events) == [E.SUGGESTION_CREATED]


async def test_401_during_reconciliation_pauses_and_releases_ticks(factory, make_tracker):
    sid, tracker, md = await _active(factory, make_tracker, [], ist(MON, 10, 11, 30))
    assert tracker.subscribed_symbols == [SYM]
    md.raise_auth = True
    md.bars[SYM].append(bar(MON, 10, 10, 101, 101.2, 94.5, 95.5))
    tracker._clock.now = ist(MON, 10, 16, 30)
    await tracker.run_cycle()
    assert tracker.state == PAUSED_AUTH_REQUIRED and tracker.subscribed_symbols == []
    row, _ = await load(factory, sid)
    assert row.status == S.ACTIVE and row.tracking_status == TrackingStatus.AUTH_REQUIRED


async def test_auth_recovery_reconciles_candles_before_resuming_ticks(factory, make_tracker):
    sid = await create(factory)
    log: list = []
    md, hub, auth = FakeMarketData(log), FakeHub(log), ["REFRESH_REQUIRED"]
    md.bars[SYM] = [ENTRY_BAR, bar(MON, 10, 10, 102, 110.5, 101.8, 110)]
    clock = Clock(ist(MON, 10, 16, 30))
    tracker = make_tracker(md=md, hub=hub, clock=clock, auth=auth)
    await tracker.run_cycle()
    assert log == []

    auth[0] = "CONNECTED"
    clock.now = ist(MON, 10, 31, 30)
    await tracker.run_cycle()
    assert log == [("fetch", SYM), ("subscribe", (SYM,))]  # candles first, then ticks
    row, events = await load(factory, sid)
    assert types(events) == [E.SUGGESTION_CREATED, E.ENTRY_TRIGGERED, E.TARGET_1_HIT]
    assert row.tracking_status == TrackingStatus.TRACKING and tracker.state == RUNNING


# ---- subscriptions / quotes -------------------------------------------------------------------------------------


async def test_subscriptions_share_the_live_data_hub_reference_count(factory, make_tracker):
    from app.services.live_data_hub import LiveDataHub

    hub = LiveDataHub()
    symbol = "NSE:RELIANCE-EQ"
    frontend_id, _ = hub.subscribe([symbol])  # an independent consumer (e.g. a browser)
    try:
        sid = await create(factory, symbol=symbol)
        tracker = make_tracker(hub=hub)
        await tracker.run_cycle()
        assert hub.subscriber_count(symbol) == 2 and hub.active_symbols == [symbol]

        async with factory() as db:
            await svc.cancel_suggestion(db, sid, "closed")
        await tracker.run_cycle()
        assert tracker.subscribed_symbols == []
        assert hub.subscriber_count(symbol) == 1  # the other consumer is untouched
        assert hub._socket is not None
    finally:
        hub.unsubscribe(frontend_id, [symbol])
        await asyncio.sleep(0.2)
    assert hub.active_symbols == []


async def test_first_tick_and_off_hours_ticks_are_ignored(make_tracker):
    tracker = make_tracker()
    tracker.ingest_tick(SYM, {"ltp": 101.0, "as_of": ist(MON, 10, 0).isoformat()}, first=True)
    tracker.ingest_tick(SYM, {"ltp": 101.0, "as_of": ist(MON, 16, 0).isoformat()})
    tracker.ingest_tick(SYM, {"ltp": 101.0, "as_of": ist(dt.date(2026, 10, 2), 10, 0).isoformat()})  # holiday
    tracker.ingest_tick(SYM, {"ltp": "bad"})
    assert tracker.metrics["ticks_ignored_subscribe_snapshot"] == 1
    assert tracker.metrics["ticks_ignored_off_hours"] == 2
    assert tracker.metrics["ticks_ignored_malformed"] == 1
    assert not tracker._ticks.get(SYM)


async def test_batched_quote_fallback_is_provisional_only(factory, make_tracker):
    from app.db.redis_client import get_redis
    from app.services.cache_service import get_json

    ids = {s: await create(factory, symbol=s) for s in ("NSE:AAA-EQ", "NSE:BBB-EQ", "NSE:CCC-EQ")}
    md = FakeMarketData()
    md.quote_prices = {
        "NSE:AAA-EQ": PriceObservation("NSE:AAA-EQ", 94.0, ist(MON, 10, 16), "QUOTE"),  # beyond the stop
        "NSE:CCC-EQ": PriceObservation("NSE:CCC-EQ", 104.0, ist(MON, 10, 16), "QUOTE"),
    }
    tracker = make_tracker(md=md)
    await tracker.run_cycle()
    tracker.ingest_tick("NSE:BBB-EQ", {"ltp": 103.0, "as_of": ist(MON, 10, 15).isoformat()}, first=True)
    tracker.ingest_tick("NSE:BBB-EQ", {"ltp": 103.0, "as_of": ist(MON, 10, 16, 20).isoformat()})  # fresh tick

    result = await tracker.run_quote_fallback()
    quote_calls = [c for c in md.calls if c[0] == "quotes"]
    assert quote_calls == [("quotes", ("NSE:AAA-EQ", "NSE:CCC-EQ"))]  # ONE batched request, stale symbols only
    assert result["received"] == ["NSE:AAA-EQ", "NSE:CCC-EQ"]

    row, events = await load(factory, ids["NSE:AAA-EQ"])
    assert row.status == S.WAITING_ENTRY and types(events) == [E.SUGGESTION_CREATED]  # nothing committed

    await tracker.flush()
    view = await get_json(get_redis(), trk.live_view_key(ids["NSE:AAA-EQ"]))
    assert view["provisional"] is True and view["committed_status"] == S.WAITING_ENTRY
    assert view["provisional_status"] == S.INVALIDATED and view["last_price_source"] == "QUOTE"


# ---- FYERS adapter: CRITICAL priority, batching, parsing ---------------------------------------------------------


async def test_fyers_adapter_uses_critical_priority_and_batches_quotes(monkeypatch):
    from app.integrations.fyers import fyers_client, request_control
    from app.integrations.fyers.request_control import RequestPriority

    seen: list[tuple] = []

    class SpyLimiter(request_control.FyersRateLimiter):
        async def acquire(self, settings, priority, category):
            seen.append((priority, category))

    monkeypatch.setattr(request_control, "_limiter", SpyLimiter())
    requests: list[httpx.Request] = []
    day_open = int(dt.datetime(2026, 9, 29, 9, 15, tzinfo=IST).timestamp())
    midnight = int(dt.datetime(2026, 9, 29, tzinfo=IST).timestamp())

    def handler(req: httpx.Request) -> httpx.Response:
        requests.append(req)
        if req.url.path.endswith("/quotes"):
            syms = req.url.params["symbols"].split(",")
            return httpx.Response(200, json={"s": "ok", "d": [  # real shape: tt is a date-stamp STRING
                {"n": s, "s": "ok", "v": {"lp": 100.0, "tt": str(midnight)}} for s in syms
            ]})
        if req.url.params["resolution"] == "D":
            return httpx.Response(200, json={"s": "ok", "candles": [[midnight, 100, 106, 99, 105.25, 1000]]})
        return httpx.Response(200, json={"s": "ok", "candles": [
            [day_open + 300, 101, 102, 100.5, 101.5, 10], [day_open, 100, 101, 99.5, 100.5, 10],
        ]})

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(fyers_client.httpx, "AsyncClient",
                        lambda **kw: real_async_client(transport=httpx.MockTransport(handler)))
    md = FyersTrackerMarketData(Settings(
        use_mock_fyers=False, fyers_client_id="test-client", fyers_secret_key="test-secret",
        fyers_access_token="test-token-never-real",
    ))

    bars = await md.five_minute_bars(SYM, TUE, TUE)
    assert [b.start for b in bars] == sorted(b.start for b in bars) and len(bars) == 2
    assert bars[0].end - bars[0].start == dt.timedelta(minutes=5) and bars[0].source == "CANDLE_5M"
    assert await md.daily_close(SYM, TUE) == 105.25

    symbols = [f"NSE:S{i:02d}-EQ" for i in range(60)]
    quotes = await md.quotes(symbols)
    quote_requests = [r for r in requests if r.url.path.endswith("/quotes")]
    assert [len(r.url.params["symbols"].split(",")) for r in quote_requests] == [50, 10]
    assert len(quotes) == 60 and quotes["NSE:S00-EQ"].source == "QUOTE"
    # tt (session-date stamp) is never used as a trade time: stamped at fetch time
    assert abs((quotes["NSE:S00-EQ"].at - dt.datetime.now(dt.UTC)).total_seconds()) < 60

    assert seen and {p for p, _ in seen} == {RequestPriority.CRITICAL}
    assert {c for _, c in seen} == {"history", "quotes"}
    assert dict(md.request_counts) == {"history_5m": 1, "history_d": 1, "quotes": 2}


def test_inconsistent_candle_is_rejected_not_repaired():
    with pytest.raises(TrackerDataError):
        trk.parse_candles({"candles": [[1790000000, 100, 99, 101, 100, 5]]}, 300, "CANDLE_5M")  # high < low


def test_cycle_wakes_after_the_bar_has_settled(make_tracker):
    tracker = make_tracker()
    now = ist(MON, 10, 31, 0)
    wake = now + dt.timedelta(seconds=tracker.seconds_until_next_cycle(now))
    assert wake > ist(MON, 10, 36, 0)  # 10:35 boundary + 60s settle, never a few ms early
    assert trk.latest_expected_bar_end(wake, tracker.settle) == ist(MON, 10, 35)


def test_latest_expected_bar_end_respects_sessions_and_holidays():
    settle = dt.timedelta(seconds=60)
    assert trk.latest_expected_bar_end(ist(MON, 10, 16, 30), settle) == ist(MON, 10, 15)
    assert trk.latest_expected_bar_end(ist(MON, 9, 10), settle) == ist(dt.date(2026, 9, 25), 15, 30)  # Fri close
    assert trk.latest_expected_bar_end(ist(dt.date(2026, 10, 2), 11, 0), settle) == ist(THU, 15, 30)  # holiday


async def test_db_writes_are_bounded(factory, make_tracker):
    sid, tracker, _ = await _active(factory, make_tracker, [bar(MON, 10, 10, 102, 104, 101.9, 103)], ist(MON, 10, 16, 30))
    assert tracker.metrics["db_commits"] == 1  # entry + same-cycle bar in ONE transaction
    for _ in range(3):
        await tracker.run_cycle()  # no new candles -> nothing changes
    await tracker.flush()
    await tracker.flush()
    assert tracker.metrics["db_commits"] == 1
    async with factory() as db:
        n = (await db.execute(select(func.count()).select_from(TradeSuggestionEvent))).scalar()
    assert n == 2
