"""Phase D: MTF daily evidence collection. Controlled scanner results are
written through the real ScannerRun/ScannerResult tables and read back with
the production get_scanner_results(); the real adapter runs with injected
generation quotes. No FYERS access, no real credentials."""

import datetime as dt
import functools

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.models.mtf_collection_run import MtfCollectionRun
from app.models.scanner_result import ScannerResult
from app.models.scanner_run import ScannerRun
from app.models.stock import Stock
from app.models.trade_suggestion import TradeSuggestion
from app.schemas.scanner import ScannerRunResponse
from app.services import mtf_daily_collection_service as col
from app.services import mtf_suggestion_adapter as ad
from app.services.mtf_daily_collection_service import MtfDailyCollector
from tests.unit.test_mtf_suggestion_adapter import candidate

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MON, TUE = dt.date(2026, 9, 28), dt.date(2026, 9, 29)


def ist(d, hh, mm):
    return dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST).astimezone(dt.UTC)


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest_asyncio.fixture
async def factory():
    import app.main  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


def fake_scanner(candidates, calls):
    async def scanner(db, request):
        calls.append(request)
        run = ScannerRun(available_capital=request.available_capital, risk_percent=request.risk_percent,
                         max_positions=request.max_positions, holding_period=request.holding_period, status="completed",
                         completed_at=dt.datetime.now(dt.UTC))
        db.add(run)
        await db.flush()
        for rank, c in enumerate(candidates, start=1):
            stock = (await db.execute(select(Stock).where(Stock.symbol == c.symbol))).scalar_one_or_none()
            if stock is None:
                stock = Stock(symbol=c.symbol, exchange="NSE", company_name="T", sector="Energy", is_fno=True,
                              is_mtf_eligible=True, is_liquid=True, is_active=True)
                db.add(stock)
                await db.flush()
            db.add(ScannerResult(run_id=run.id, stock_id=stock.id, symbol=c.symbol, rank=rank, score=c.score,
                                 signal_quality=c.signal_quality, payload=c.model_dump(mode="json")))
        await db.commit()
        return ScannerRunResponse(run_id=run.id, status="completed", generated_at=run.completed_at,
                                  holding_period="1-4 weeks", stocks_analyzed=len(candidates), stocks_rejected=0,
                                  stocks_selected=len(candidates), candidates=candidates)
    return scanner


def ok_quote(price):
    return ad.GenerationQuote(status=ad.PRICE_OK, price=price, at=dt.datetime.now(dt.UTC), fetched_at=dt.datetime.now(dt.UTC),
                              source="TICK", market_status="MARKET_OPEN_LIVE")


def make(factory, clock, candidates=None, quotes=None, auth="CONNECTED", dry_run=False, scanner_calls=None, **kw):
    settings = Settings(enable_mtf_daily_collection=True, mtf_daily_collection_dry_run=dry_run, use_mock_fyers=False, **kw)
    cands = candidates if candidates is not None else [candidate(symbol="NSE:A-EQ"), candidate(symbol="NSE:B-EQ", close=110.0)]
    q = quotes if quotes is not None else {"NSE:A-EQ": ok_quote(102.1), "NSE:B-EQ": ok_quote(110.2)}
    return MtfDailyCollector(
        settings=settings, session_factory=factory, clock=clock, auth_status=lambda: auth,
        scanner=fake_scanner(cands, scanner_calls if scanner_calls is not None else []),
        adapter=functools.partial(ad.run_mtf_adapter, quotes=q),
    )


async def runs(factory):
    async with factory() as db:
        return list((await db.execute(select(MtfCollectionRun).order_by(MtfCollectionRun.id))).scalars().all())


# ---- windows ---------------------------------------------------------------------------------


def test_scan_window_only_uses_completed_sessions():
    s = Settings()
    assert col.scan_session_due(ist(MON, 11, 0), s) is None  # Monday in session: forming candle
    assert col.scan_session_due(ist(MON, 15, 45), s) is None  # closed but before 16:00
    assert col.scan_session_due(ist(MON, 16, 0), s) == MON
    assert col.scan_session_due(ist(TUE, 8, 30), s) == MON  # late catch-up before pre-open
    assert col.scan_session_due(ist(TUE, 9, 0), s) is None  # pre-open: never scan
    assert col.scan_session_due(dt.datetime(2026, 10, 3, 6, 0, tzinfo=dt.UTC), s) == dt.date(2026, 10, 1)  # Sat after Fri holiday


def test_generate_window():
    s = Settings()
    assert col.generate_window(ist(TUE, 9, 20), s) == (None, False)
    assert col.generate_window(ist(TUE, 9, 35), s) == (TUE, True)
    assert col.generate_window(ist(TUE, 11, 0), s) == (TUE, False)
    assert col.generate_window(ist(dt.date(2026, 10, 2), 9, 35), s) == (None, False)  # NSE holiday


# ---- behaviour ---------------------------------------------------------------------------------


async def test_collection_is_disabled_by_default(factory):
    assert Settings.model_fields["enable_mtf_daily_collection"].default is False
    assert Settings.model_fields["mtf_daily_collection_dry_run"].default is True
    c = MtfDailyCollector(settings=Settings(), session_factory=factory)
    assert await c.start() is False and c.state == "DISABLED"


async def test_single_scan_per_session_and_restart_dedup(factory):
    calls = []
    clock = Clock(ist(MON, 16, 5))
    first = make(factory, clock, scanner_calls=calls)
    out = await first.tick()
    assert out["scan"]["status"] == col.COMPLETED
    await first.tick()
    restarted = make(factory, clock, scanner_calls=calls)  # new process, same DB
    again = await restarted.tick()
    assert again["scan"]["status"] == "ALREADY_DONE"
    assert len(calls) == 1
    (row,) = [r for r in await runs(factory) if r.stage == "SCAN"]
    assert row.stage == "SCAN" and row.session_date == MON and row.scanner_run_id is not None
    assert row.summary["candle_basis"] == "COMPLETED_DAILY_CANDLES" and row.candidates == 2


async def test_generate_persists_only_eligible_and_records_collection_metadata(factory):
    clock = Clock(ist(MON, 16, 5))
    c = make(factory, clock)
    await c.tick()
    clock.now = ist(TUE, 9, 35)
    out = await c.tick()
    assert out["generate"]["status"] == col.COMPLETED and out["generate"]["persisted"] == 1
    gen = (await runs(factory))[-1]
    assert (gen.candidates, gen.eligible, gen.rejected, gen.persisted) == (2, 1, 1, 1)
    assert gen.summary["results"][1]["rejection_reasons"]  # the close-clamp candidate
    async with factory() as db:
        rows = (await db.execute(select(TradeSuggestion))).scalars().all()
    assert [r.symbol for r in rows] == ["NSE:A-EQ"]
    meta = rows[0].research_metadata
    assert meta["collection_run_id"] == gen.id and meta["scan_session_date"] == MON.isoformat()
    assert meta["scan_candle_basis"] == "COMPLETED_DAILY_CANDLES" and rows[0].scanner_run_id == gen.scanner_run_id
    # repeated tick / restart: no second generation, no duplicate suggestion
    await make(factory, clock).tick()
    async with factory() as db:
        assert (await db.execute(select(func.count()).select_from(TradeSuggestion))).scalar() == 1


async def test_zero_valid_setups_is_recorded_as_no_valid_setup(factory):
    clock = Clock(ist(MON, 16, 5))
    stale = {"NSE:A-EQ": ad.GenerationQuote(status=ad.PRICE_STALE, detail="old"),
             "NSE:B-EQ": ad.GenerationQuote(status=ad.PRICE_STALE, detail="old")}
    c = make(factory, clock, quotes=stale)
    await c.tick()
    clock.now = ist(TUE, 9, 40)
    assert (await c.tick())["generate"]["status"] == col.NO_VALID_SETUP
    async with factory() as db:
        assert (await db.execute(select(func.count()).select_from(TradeSuggestion))).scalar() == 0


async def test_dry_run_persists_nothing(factory):
    clock = Clock(ist(MON, 16, 5))
    c = make(factory, clock, dry_run=True)
    await c.tick()
    clock.now = ist(TUE, 9, 35)
    out = await c.tick()
    assert out["generate"]["status"] == col.COMPLETED and out["generate"]["persisted"] == 0
    async with factory() as db:
        assert (await db.execute(select(func.count()).select_from(TradeSuggestion))).scalar() == 0
    assert all(r.dry_run for r in await runs(factory))


async def test_auth_required_records_nothing_and_retries(factory):
    auth = ["REFRESH_REQUIRED"]
    clock = Clock(ist(MON, 16, 5))
    calls = []
    c = make(factory, clock, scanner_calls=calls)
    c._auth_status = lambda: auth[0]
    assert (await c.tick())["scan"]["status"] == "WAITING_FOR_AUTH"
    assert [r for r in await runs(factory) if r.stage == "SCAN"] == [] and calls == []
    auth[0] = "CONNECTED"  # reconnect inside the window
    assert (await c.tick())["scan"]["status"] == col.COMPLETED and len(calls) == 1


async def test_generate_without_scan_and_missed_window_are_recorded(factory):
    clock = Clock(ist(TUE, 9, 35))
    c = make(factory, clock)
    assert (await c.tick())["generate"]["status"] == col.SKIPPED_NO_SCAN
    clock.now = ist(dt.date(2026, 9, 30), 12, 0)  # restarted after Wednesday's slot
    assert (await c.tick())["generate"]["status"] == col.SKIPPED_MISSED_WINDOW
    assert (await c.tick())["generate"]["status"] == "ALREADY_DONE"


async def test_interrupted_run_is_marked_and_retry_is_bounded(factory):
    clock = Clock(ist(MON, 16, 5))
    async with factory() as db:
        db.add(MtfCollectionRun(stage="SCAN", session_date=MON, dry_run=False, forced=False,
                                dedup_key=col.dedup_key("SCAN", MON, False), status=col.RUNNING,
                                started_at=clock.now, summary={}))
        await db.commit()
    c = make(factory, clock, mtf_daily_max_attempts=2)
    assert await c.recover_interrupted() == 1
    assert (await c.tick())["scan"]["status"] == col.COMPLETED  # attempt 2 of 2
    statuses = [r.status for r in await runs(factory) if r.stage == "SCAN"]
    assert statuses == [col.FAILED_INTERRUPTED, col.COMPLETED]


async def test_forced_operator_run_does_not_use_the_dedup_key(factory):
    clock = Clock(ist(MON, 16, 5))
    calls = []
    c = make(factory, clock, scanner_calls=calls)
    await c.tick()
    out = await c.run_scan(MON, forced=True)
    assert out["status"] == col.COMPLETED and len(calls) == 2
    forced = [r for r in await runs(factory) if r.stage == "SCAN"][-1]
    assert forced.forced is True and forced.dedup_key is None


async def test_scan_is_refused_while_a_daily_candle_can_be_forming(factory):
    calls = []
    c = make(factory, Clock(ist(TUE, 11, 0)), scanner_calls=calls)  # NSE in session
    for forced in (False, True):
        out = await c.run_scan(TUE, forced=forced)
        assert out["status"] == "REFUSED_OUTSIDE_COMPLETED_CANDLE_WINDOW"
    assert calls == [] and [r for r in await runs(factory) if r.stage == "SCAN"] == []


async def test_tracker_picks_up_collected_suggestions(factory):
    from tests.unit.test_suggestion_tracker_service import FakeHub, FakeMarketData

    from app.services.suggestion_tracker_service import SuggestionTracker

    clock = Clock(ist(MON, 16, 5))
    c = make(factory, clock)
    await c.tick()
    clock.now = ist(TUE, 9, 35)
    await c.tick()
    hub = FakeHub()
    tracker = SuggestionTracker(settings=Settings(enable_suggestion_tracker=True), session_factory=factory,
                                market_data=FakeMarketData(), hub=hub, clock=Clock(ist(TUE, 9, 50)),
                                auth_status=lambda: "CONNECTED")
    await tracker.run_cycle()
    assert tracker.subscribed_symbols == ["NSE:A-EQ"] and hub.refs["NSE:A-EQ"] == 1
    await tracker._release_all_subscriptions()
