"""Phase C: MTF suggestion adapter. Candidates are built through the REAL
scenario_engine.build_scenarios(), so provenance reproduction is tested
against actual engine output. No test touches the real FYERS session:
quotes are GenerationQuote fixtures or an httpx.MockTransport."""

import datetime as dt

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.base import Base
from app.engines import scenario_engine
from app.engines.technical_engine import TechnicalResult
from app.models.trade_suggestion import TradeSuggestion
from app.schemas.common import DataQuality, InstitutionalFootprint, PositionSizing, SetupDetection
from app.schemas.scanner import CandidateResponse
from app.schemas.stock import FnoData, FundamentalData, NewsData, RelativeStrengthData, SectorData, TechnicalData, VolumeData
from app.services import mtf_suggestion_adapter as ad
from app.services import suggestion_service as svc
from app.services.mtf_suggestion_adapter import GenerationQuote

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
LIVE_NOW = dt.datetime(2026, 9, 28, 10, 0, tzinfo=IST).astimezone(dt.UTC)  # Monday, market open

ENABLED_DRY = Settings(enable_mtf_suggestion_adapter=True, mtf_suggestion_dry_run=True)
ENABLED_PERSIST = Settings(enable_mtf_suggestion_adapter=True, mtf_suggestion_dry_run=False)


def technical(support=100.0, resistance=115.0, atr=4.0, **kw) -> dict:
    base = dict(
        ema_20=101.0, ema_50=support, ema_200=90.0, rsi_14=55.0, atr_14=atr, adx_14=24.0, vwap=101.5,
        recent_high_20d=resistance, recent_low_20d=support - 1 if support is not None else None,
        support_level=support, resistance_level=resistance, trend_structure="UPTREND",
        breakout_status="NO_BREAKOUT", pullback_status="PULLBACK_TO_SUPPORT",
    )
    base.update(kw)
    return base


def candidate(close=102.0, symbol="NSE:TEST-EQ", score=60.0, **tech_kw) -> CandidateResponse:
    tech = technical(**tech_kw)
    scen = scenario_engine.build_scenarios(close, TechnicalResult(**tech))  # the real production engine
    return CandidateResponse(
        symbol=symbol, company_name="Test Co", sector="Energy", score=score, score_components=[],
        signal_quality="MEDIUM", price=round(close, 2), entry_zone_low=scen.entry_zone_low,
        entry_zone_high=scen.entry_zone_high, invalidation=scen.invalidation, scenarios=scen,
        setup=SetupDetection(setup_type="PULLBACK"),
        institutional_footprint=InstitutionalFootprint(institutional_footprint_score=40.0,
                                                       institutional_footprint_level="MODERATE"),
        technical=TechnicalData(**tech), volume=VolumeData(volume_ratio=1.3),
        fno=FnoData(is_available=False), fundamentals=FundamentalData(is_available=False),
        relative_strength=RelativeStrengthData(label="OUTPERFORM", vs_nifty_pct_20d=2.0),
        sector_context=SectorData(sector_strength_label="STRONG", relative_strength=RelativeStrengthData(label="OUTPERFORM")),
        news=NewsData(),
        position_sizing=PositionSizing(
            available_capital=100000, risk_percent=1, entry_price=close, invalidation_price=scen.invalidation,
            risk_per_share=1.0, max_rupee_risk=1000.0, quantity=1, capital_required=close, capital_utilization_pct=0.1,
        ),
        data_quality=DataQuality(data_quality_score=80.0),
    )


def ok_quote(price=102.1) -> GenerationQuote:
    return GenerationQuote(status=ad.PRICE_OK, price=price, at=LIVE_NOW - dt.timedelta(seconds=2), fetched_at=LIVE_NOW,
                           source="QUOTE", market_status="MARKET_OPEN_LIVE")


@pytest_asyncio.fixture
async def factory():
    import app.main  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    await engine.dispose()


async def count(factory) -> int:
    async with factory() as db:
        return (await db.execute(select(func.count()).select_from(TradeSuggestion))).scalar()


# ---- provenance audit ------------------------------------------------------------------------


def test_pullback_candidate_levels_are_structure_and_atr_derived():
    lv = ad.classify_levels(candidate(close=102.0))  # support 100, ATR 4 -> zone 101-103, stop 99
    assert (lv["entry_low"].price, lv["entry_low"].quality) == (101.0, "ATR_DERIVED")
    assert (lv["entry_high"].price, lv["entry_high"].quality) == (103.0, "ATR_DERIVED")
    assert (lv["stop_loss"].price, lv["stop_loss"].quality) == (99.0, "ATR_DERIVED")
    assert (lv["target_1"].price, lv["target_1"].quality) == (115.0, "VERIFIED_STRUCTURE")
    assert (lv["target_2"].price, lv["target_2"].quality) == (123.0, "ATR_DERIVED")
    assert "EMA50" in lv["entry_low"].provenance or "20D low" in lv["entry_low"].provenance


def test_last_close_clamp_is_classified_fallback():
    lv = ad.classify_levels(candidate(close=110.0))  # max(110, 103) -> 110 = scan close, not a level
    assert lv["entry_high"].price == 110.0 and lv["entry_high"].quality == "FALLBACK"
    assert "clamp" in lv["entry_high"].provenance
    assert lv["entry_low"].quality == "ATR_DERIVED"


def test_placeholder_paths_are_fallback():
    no_atr = ad.classify_levels(candidate(atr=None))
    assert {no_atr[k].quality for k in ("entry_low", "entry_high", "stop_loss", "target_2")} == {"FALLBACK"}
    assert no_atr["target_1"].quality == "VERIFIED_STRUCTURE"
    no_res = ad.classify_levels(candidate(resistance=None))
    assert no_res["target_1"].quality == "FALLBACK" and "close*1.05" in no_res["target_1"].provenance


# ---- evaluation -----------------------------------------------------------------------------------


def test_valid_candidate_is_eligible_with_would_create():
    ev, req = ad.evaluate_candidate(candidate(), 1, 7, ok_quote())
    assert ev.eligible and ev.rejection_reasons == [] and req is not None
    assert ev.would_create["entry_low"] == 101.0 and ev.would_create["entry_high"] == 103.0
    assert ev.would_create["generation_market_price"] == 102.1 and ev.would_create["market_status"] == "MARKET_OPEN_LIVE"
    assert req.generation_price_source == "QUOTE" and req.generated_at == LIVE_NOW


@pytest.mark.parametrize("kw,level", [
    ({"close": 110.0}, "entry_high"),  # clamp -> FALLBACK entry
    ({"atr": None}, "entry_low"),  # placeholder ATR -> FALLBACK entry
    ({"resistance": None}, "target_1"),  # placeholder resistance -> FALLBACK T1
    ({"support": None}, "stop_loss"),  # placeholder support -> FALLBACK stop
])
def test_fallback_critical_levels_are_rejected(kw, level):
    ev, req = ad.evaluate_candidate(candidate(**kw), 1, 7, ok_quote())
    assert not ev.eligible and req is None
    assert any(r.startswith(level) and "FALLBACK" in r for r in ev.rejection_reasons), ev.rejection_reasons


def test_invalid_geometry_is_rejected():
    ev, req = ad.evaluate_candidate(candidate(resistance=102.5, recent_high_20d=102.5), 1, 7, ok_quote())
    assert req is None and any("target_1" in r and "must be above entry_high" in r for r in ev.rejection_reasons)


@pytest.mark.parametrize("status", [ad.PRICE_STALE, ad.PRICE_UNAVAILABLE, ad.PRICE_MOCK, ad.PRICE_AUTH_REQUIRED,
                                    ad.PRICE_MARKET_CLOSED])
def test_non_live_generation_price_is_rejected(status):
    ev, req = ad.evaluate_candidate(candidate(), 1, 7, GenerationQuote(status=status, detail="x"))
    assert req is None and any(r.startswith(f"generation price {status}") for r in ev.rejection_reasons)


def test_stale_candidate_data_is_rejected():
    c = candidate()
    c.data_quality.stale_data.append("price_history")
    ev, req = ad.evaluate_candidate(c, 1, 7, ok_quote())
    assert req is None and any("stale data" in r for r in ev.rejection_reasons)


def test_evidence_snapshot_captures_generation_time_candidate():
    ev, req = ad.evaluate_candidate(candidate(score=61.5), 3, 42, ok_quote(),
                                    research_context={"research_confirmation_score": 44.0})
    snap = req.evidence_snapshot
    assert snap["mtf_rank"] == 3 and snap["mtf_score"] == 61.5 and snap["scanner_run_id"] == 42
    assert snap["technical"]["rsi_14"] == 55.0 and snap["technical"]["adx_14"] == 24.0
    assert snap["volume"]["volume_ratio"] == 1.3 and snap["relative_strength"]["label"] == "OUTPERFORM"
    assert snap["institutional_footprint_proxy"]["level"] == "MODERATE"
    assert snap["generation_quote"]["price"] == 102.1 and snap["generation_quote"]["market_status"] == "MARKET_OPEN_LIVE"
    assert snap["levels"]["entry_high"]["quality"] == "ATR_DERIVED"
    assert snap["reward_risk"]["reward_risk_t1_from_entry_high"] == 3.0  # (115-103)/(103-99)
    assert snap["research_context"] == {"research_confirmation_score": 44.0}


# ---- modes / persistence ----------------------------------------------------------------------------


async def test_adapter_disabled_does_nothing(factory):
    async with factory() as db:
        out = await ad.run_mtf_adapter(db, [(1, candidate())], 1, settings=Settings())
    assert out == {"mode": "DISABLED", "evaluated": 0, "results": []}
    assert Settings().enable_mtf_suggestion_adapter is False and Settings().mtf_suggestion_dry_run is True
    assert Settings.model_fields["enable_mtf_suggestion_adapter"].default is False
    assert Settings.model_fields["mtf_suggestion_dry_run"].default is True


async def test_dry_run_persists_nothing(factory):
    cands = [(1, candidate(symbol="NSE:A-EQ")), (2, candidate(symbol="NSE:B-EQ", close=110.0))]
    quotes = {"NSE:A-EQ": ok_quote(), "NSE:B-EQ": ok_quote(110.2)}
    async with factory() as db:
        out = await ad.run_mtf_adapter(db, cands, 9, settings=ENABLED_DRY, quotes=quotes)
    assert out["mode"] == "DRY_RUN" and (out["eligible"], out["rejected"], out["persisted"]) == (1, 1, 0)
    assert out["results"][0]["would_create"]["symbol"] == "NSE:A-EQ"
    assert out["results"][1]["would_create"] is None and out["results"][1]["rejection_reasons"]
    assert await count(factory) == 0
    assert ad.last_run()["scanner_run_id"] == 9


async def test_controlled_persistence_and_duplicate_handling(factory):
    cands = [(1, candidate(symbol="NSE:A-EQ")), (2, candidate(symbol="NSE:B-EQ", close=110.0))]
    quotes = {"NSE:A-EQ": ok_quote(), "NSE:B-EQ": ok_quote(110.2)}
    async with factory() as db:
        out = await ad.run_mtf_adapter(db, cands, 9, settings=ENABLED_PERSIST, quotes=quotes)
    assert out["persisted"] == 1 and out["results"][1]["creation_status"] is None  # rejected -> never created
    sid = out["results"][0]["suggestion_id"]
    async with factory() as db:
        row = await db.get(TradeSuggestion, sid)
        events = await svc.list_events(db, sid)
    assert row.status == "WAITING_ENTRY" and float(row.generation_market_price) == 102.1
    assert row.generation_price_source == "QUOTE" and row.market_status == "MARKET_OPEN_LIVE"
    assert row.level_quality["entry_high"]["quality"] == "ATR_DERIVED" and row.scanner_run_id == 9
    assert row.evidence_snapshot["mtf_rank"] == 1 and [e.event_type for e in events] == ["SUGGESTION_CREATED"]

    async with factory() as db:
        again = await ad.run_mtf_adapter(db, cands[:1], 10, settings=ENABLED_PERSIST, quotes=quotes)
    assert again["results"][0]["creation_status"] == "DUPLICATE_OPEN" and await count(factory) == 1


async def test_research_context_with_decimal_db_values_persists(factory):
    """Regression (found in the 2026-09-29 live controlled test): research
    context read from Numeric DB columns carries Decimal values."""
    from decimal import Decimal

    ctx = {"NSE:TEST-EQ": {"research_confirmation_score": Decimal("49.31"), "india_vix": Decimal("14.560")}}
    async with factory() as db:
        out = await ad.run_mtf_adapter(db, [(1, candidate())], 1, settings=ENABLED_PERSIST,
                                       quotes={"NSE:TEST-EQ": ok_quote()}, research_context=ctx)
    async with factory() as db:
        row = await db.get(TradeSuggestion, out["results"][0]["suggestion_id"])
    assert row.evidence_snapshot["research_context"] == {"research_confirmation_score": 49.31, "india_vix": 14.56}


async def test_candidates_score_and_order_are_never_modified(factory):
    cands = [(1, candidate(symbol="NSE:A-EQ", score=70.0)), (2, candidate(symbol="NSE:B-EQ", score=65.0))]
    before = [(r, c.model_dump(mode="json")) for r, c in cands]
    async with factory() as db:
        await ad.run_mtf_adapter(db, cands, 1, settings=ENABLED_PERSIST,
                                 quotes={"NSE:A-EQ": ok_quote(), "NSE:B-EQ": ok_quote()})
    assert [(r, c.model_dump(mode="json")) for r, c in cands] == before


async def test_tracker_picks_up_a_persisted_suggestion(factory):
    from tests.unit.test_suggestion_tracker_service import Clock, FakeHub, FakeMarketData

    from app.services.suggestion_tracker_service import SuggestionTracker

    async with factory() as db:
        out = await ad.run_mtf_adapter(db, [(1, candidate())], 1, settings=ENABLED_PERSIST,
                                       quotes={"NSE:TEST-EQ": ok_quote()})
    sid = out["results"][0]["suggestion_id"]
    hub = FakeHub()
    tracker = SuggestionTracker(
        settings=Settings(enable_suggestion_tracker=True), session_factory=factory, market_data=FakeMarketData(),
        hub=hub, clock=Clock(LIVE_NOW + dt.timedelta(minutes=6)), auth_status=lambda: "CONNECTED",
    )
    await tracker.run_cycle()
    assert sid in tracker.tracked and tracker.subscribed_symbols == ["NSE:TEST-EQ"] and hub.refs["NSE:TEST-EQ"] == 1
    await tracker._release_all_subscriptions()


# ---- generation quotes (FYERS path, MockTransport) -------------------------------------------------------


async def test_generation_quote_gates_without_fyers_calls():
    mock = await ad.fetch_generation_quotes(["NSE:A-EQ"], Settings(use_mock_fyers=True), now=LIVE_NOW)
    assert mock["NSE:A-EQ"].status == ad.PRICE_MOCK
    live = Settings(use_mock_fyers=False, fyers_client_id="c", fyers_secret_key="s", fyers_access_token="t")
    closed = await ad.fetch_generation_quotes(["NSE:A-EQ"], live, now=LIVE_NOW.replace(hour=12))  # 17:30 IST
    assert closed["NSE:A-EQ"].status == ad.PRICE_MARKET_CLOSED
    auth = await ad.fetch_generation_quotes(["NSE:A-EQ"], live, now=LIVE_NOW, auth_status="REFRESH_REQUIRED")
    assert auth["NSE:A-EQ"].status == ad.PRICE_AUTH_REQUIRED


LIVE = Settings(use_mock_fyers=False, fyers_client_id="c", fyers_secret_key="s", fyers_access_token="t")


async def test_generation_price_comes_from_one_hub_read_with_freshness_check():
    calls = []
    fresh = (dt.datetime.now(dt.UTC) - dt.timedelta(seconds=2)).isoformat()
    old = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()

    async def reader(symbols, settings=None):
        calls.append(tuple(symbols))
        return {"NSE:OK-EQ": {"symbol": "NSE:OK-EQ", "ltp": 100.5, "as_of": fresh},
                "NSE:OLD-EQ": {"symbol": "NSE:OLD-EQ", "ltp": 99.0, "as_of": old}, "NSE:GONE-EQ": None}

    symbols = ["NSE:OK-EQ", "NSE:OLD-EQ", "NSE:GONE-EQ"]
    out = await ad.fetch_generation_quotes(symbols, LIVE, now=LIVE_NOW, auth_status="CONNECTED", live_reader=reader)
    assert calls == [tuple(symbols)]  # one shared-hub subscription for all candidates
    ok = out["NSE:OK-EQ"]
    assert ok.status == ad.PRICE_OK and ok.source == "TICK" and ok.price == 100.5 and ok.market_status == "MARKET_OPEN_LIVE"
    assert out["NSE:OLD-EQ"].status == ad.PRICE_STALE
    assert out["NSE:GONE-EQ"].status == ad.PRICE_UNAVAILABLE


async def test_gated_states_never_open_a_subscription():
    async def reader(symbols, settings=None):
        raise AssertionError("must not subscribe")

    for settings, now, auth in ((Settings(use_mock_fyers=True), LIVE_NOW, "CONNECTED"),
                                (LIVE, LIVE_NOW.replace(hour=12), "CONNECTED"), (LIVE, LIVE_NOW, "LOGIN_REQUIRED")):
        out = await ad.fetch_generation_quotes(["NSE:A-EQ"], settings, now=now, auth_status=auth, live_reader=reader)
        assert out["NSE:A-EQ"].status in (ad.PRICE_MOCK, ad.PRICE_MARKET_CLOSED, ad.PRICE_AUTH_REQUIRED)


async def test_auth_failure_while_reading_live_data_is_auth_required():
    from app.core.exceptions import FyersAuthRequiredError

    async def reader(symbols, settings=None):
        raise FyersAuthRequiredError("expired", status_code=401)

    out = await ad.fetch_generation_quotes(["NSE:A-EQ", "NSE:B-EQ"], LIVE, now=LIVE_NOW, auth_status="CONNECTED",
                                           live_reader=reader)
    assert {q.status for q in out.values()} == {ad.PRICE_AUTH_REQUIRED}
