"""Phase D: evidence dataset, analytics, segments. Controlled suggestions are
created through the internal service with a generation-time snapshot;
outcomes come from controlled observations. No FYERS."""

import datetime as dt

import pytest

from app.core.suggestion_constants import LevelQuality
from app.engines.suggestion_state_engine import Tick
from app.schemas.suggestion import LevelInput, SuggestionCreateRequest
from app.services import suggestion_analytics_service as an
from app.services import suggestion_service as svc

V, A = LevelQuality.VERIFIED_STRUCTURE.value, LevelQuality.ATR_DERIVED.value
NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def snapshot(score, rank, rsi=40.0, atr=4.0, research=None) -> dict:
    return {
        "snapshot_version": 2, "mtf_rank": rank, "mtf_score": score, "signal_quality": "MEDIUM",
        "technical": {"trend_structure": "STRONG_DOWNTREND", "rsi_14": rsi, "adx_14": 22.0, "atr_14": atr,
                      "ema_20": 103.0, "ema_50": 105.0, "ema_200": 110.0, "breakout_status": "NO_BREAKOUT"},
        "volume": {"volume_ratio": 0.9}, "relative_strength": {"label": "OUTPERFORM", "vs_nifty_pct_20d": 2.0},
        "sector_context": {"sector": "Energy", "strength": "STRONG", "market_regime": "RISK_OFF"},
        "institutional_footprint_proxy": {"level": "NEUTRAL", "evidence": [
            {"label": "Delivery behaviour proxy", "detail": "delivery 48% vs 20D avg 41%"}]},
        "fno": {"positioning_proxy": "LONG_BUILDUP_PROXY"}, "research_context": research,
    }


def request(symbol, score, rank, gen_price=101.0, **kw) -> SuggestionCreateRequest:
    levels = {"entry_low": LevelInput(price=100.0, quality=A, provenance="support+0.25ATR"),
              "entry_high": LevelInput(price=102.0, quality=A, provenance="support+0.75ATR"),
              "target_1": LevelInput(price=110.0, quality=V, provenance="20D high"),
              "target_2": LevelInput(price=118.0, quality=A, provenance="20D high+2ATR"),
              "stop_loss": LevelInput(price=98.0, quality=A, provenance="support-0.25ATR")}
    return SuggestionCreateRequest(
        scanner_type="MTF", market="NSE_EQ", symbol=symbol, instrument_type="EQUITY", direction="LONG",
        setup_type="PULLBACK", generated_at=kw.pop("generated_at", NOW - dt.timedelta(hours=2)),
        generation_market_price=gen_price, generation_price_source="TICK", market_status="MARKET_OPEN_LIVE",
        data_quality="DQ_SCORE_80.0", levels=levels, score=score,
        evidence_snapshot=snapshot(score, rank, **kw),
        research_metadata={"scan_candle_basis": "COMPLETED_DAILY_CANDLES", "collection_run_id": 1},
    )


async def make(db, symbol, score, rank, prices=None, gen_price=101.0, **kw) -> int:
    req = request(symbol, score, rank, gen_price, **kw)
    sid = (await svc.create_suggestion(db, req)).suggestion_id
    if prices:
        await svc.apply_observations(db, sid, [Tick(at=req.generated_at + dt.timedelta(minutes=i + 1), price=p)
                                               for i, p in enumerate(prices)])
    return sid


async def seed(db):
    ids = {}
    ids["win"] = await make(db, "NSE:WIN-EQ", 62, 1, [101.0, 106.0, 110.5, 118.5])  # T1 then T2
    ids["loss"] = await make(db, "NSE:LOSS-EQ", 55, 2, [101.0, 97.5])  # FAILED_STOP
    ids["partial"] = await make(db, "NSE:PART-EQ", 48, 4, [101.0, 110.2, 97.9])  # PARTIAL_SUCCESS
    ids["inv"] = await make(db, "NSE:INV-EQ", 45, 5, [97.0], gen_price=104.0)  # INVALIDATED_BEFORE_ENTRY
    ids["pull"] = await make(db, "NSE:PULL-EQ", 41, 7, [103.5, 101.5], gen_price=104.0)  # entered from above: pullback
    noe = await make(db, "NSE:NOE-EQ", 38, 8, gen_price=104.0)
    row = await svc.get_suggestion(db, noe)
    await svc.apply_session_close(db, noe, row.entry_deadline_session_date, None, NOW, "CANDLE_D")
    ids["noe"] = noe
    exp = await make(db, "NSE:EXP-EQ", 35, 9, [101.0, 104.0])
    row = await svc.get_suggestion(db, exp)
    await svc.apply_session_close(db, exp, row.holding_deadline_session_date, 103.0, NOW, "CANDLE_D")
    ids["exp"] = exp
    return ids


async def test_dataset_rows_are_generation_time_features_plus_outcomes(app_client, db_session):
    ids = await seed(db_session)
    body = (await app_client.get("/api/suggestions/analysis-dataset")).json()
    rows = {r["id"]: r for r in body["rows"]}
    win = rows[ids["win"]]
    assert win["mtf_rank"] == 1 and win["rsi_14"] == 40.0 and win["atr_pct"] == pytest.approx(3.96, abs=0.01)
    assert win["price_vs_ema20"] == "BELOW" and win["ema20_above_ema50"] is False
    assert win["delivery_evidence"] == "delivery 48% vs 20D avg 41%"
    assert win["scan_candle_basis"] == "COMPLETED_DAILY_CANDLES" and win["collection_run_id"] == 1
    assert win["level_quality_signature"] == "entry_low:ATR|entry_high:ATR|target_1:VS|stop_loss:ATR"
    # ATR feasibility (ATR 4): T1 110 from generation 101 = 2.25 ATR; stop 98 = 0.75 ATR
    assert win["target_1_distance_atr"] == 2.25 and win["stop_distance_atr"] == 0.75
    assert win["target_2_distance_atr"] == 4.25 and win["nominal_rr_t1_from_entry_high"] == 2.0
    assert win["target_1_distance_atr_from_entry"] == 2.25 and win["mfe_atr"] == 4.375  # (118.5-101)/4
    assert win["research_confirmation_score"] is None  # not captured -> missing, never invented
    assert win["entry_classification"] == "IMMEDIATE_ENTRY"
    assert rows[ids["pull"]]["entry_classification"] == "PULLBACK_ENTRY"
    assert rows[ids["pull"]]["distance_to_entry_pct"] == pytest.approx(-1.923, abs=0.001)
    assert rows[ids["noe"]]["entry_classification"] == "NO_ENTRY"
    assert rows[ids["inv"]]["entry_classification"] == "INVALIDATED_BEFORE_ENTRY"
    assert rows[ids["exp"]]["expiry_time"] is not None and rows[ids["loss"]]["stop_time"] is not None


async def test_analytics_denominators_and_intervals(app_client, db_session):
    await seed(db_session)
    body = (await app_client.get("/api/suggestions/analytics")).json()
    assert body["suggestions_generated"] == 7
    # entry resolved = 5 triggered + NO_ENTRY + INVALIDATED
    assert body["trigger_rate"]["count"] == 5 and body["trigger_rate"]["n"] == 7
    # completed trades: win(T2), loss, partial, expired -- NOT no-entry / invalidated / the open pullback
    assert body["completed_trades"] == body["sample_size"] == 4
    assert body["win_rate"] == {"count": 1, "n": 4, "pct": 25.0, "ci95_pct": body["win_rate"]["ci95_pct"]}
    lo, hi = body["win_rate"]["ci95_pct"]
    assert lo < 25 < hi
    assert body["target_1_hit_rate"]["count"] == 2  # win + partial
    assert body["target_2_hit_rate"]["count"] == 1
    assert body["stop_rate"]["count"] == 2 and body["failed_stop_rate"]["count"] == 1
    assert body["partial_success_rate"]["count"] == 1 and body["expired_rate"]["count"] == 1
    assert body["entry_classification"]["IMMEDIATE_ENTRY"] == 4
    assert body["entry_classification"]["PULLBACK_ENTRY"] == 1
    assert body["median_minutes_to_entry"] == 1.0
    tf = body["target_feasibility"]
    assert tf["median_target_1_distance_atr_from_entry"] is not None and tf["mfe_reached_target_1_distance"]["n"] == 5
    assert body["stop_feasibility"]["median_stop_distance_atr_from_entry"] is not None
    assert "profitable" not in str(body).lower().replace("not evidence of profitability", "")


@pytest.mark.parametrize("by,expected", [
    ("mtf_score_bucket", {"30-40", "40-50", "50-60", "60-70"}),
    ("rank_bucket", {"1-3", "4-6", "7-10"}),
    ("entry_classification", {"IMMEDIATE_ENTRY", "PULLBACK_ENTRY", "NO_ENTRY", "INVALIDATED_BEFORE_ENTRY"}),
    ("research_confirmation_bucket", {"UNAVAILABLE"}),
])
async def test_segments_group_outcomes(app_client, db_session, by, expected):
    await seed(db_session)
    body = (await app_client.get("/api/suggestions/segments", params={"by": by})).json()
    assert {g["segment"] for g in body["groups"]} == expected
    assert sum(g["suggestions"] for g in body["groups"]) == 7


async def test_score_bucket_counts(app_client, db_session):
    await seed(db_session)
    groups = {g["segment"]: g for g in (await app_client.get("/api/suggestions/segments", params={"by": "mtf_score_bucket"})).json()["groups"]}
    assert groups["60-70"]["win_rate"]["count"] == 1 and groups["60-70"]["completed_trades"] == 1
    assert groups["30-40"]["no_entry"] == 1 and groups["40-50"]["invalidated_before_entry"] == 1


async def test_unknown_segment_is_rejected(app_client):
    assert (await app_client.get("/api/suggestions/segments", params={"by": "magic"})).status_code == 422


async def test_analytics_endpoints_never_call_fyers(app_client, db_session, monkeypatch):
    from app.integrations.fyers.fyers_client import FyersClient

    async def _forbidden(*a, **k):
        raise AssertionError("analytics must not call FYERS")

    monkeypatch.setattr(FyersClient, "_send", _forbidden)
    await seed(db_session)
    for path in ("/api/suggestions/analytics", "/api/suggestions/analysis-dataset",
                 "/api/suggestions/segments?by=trend", "/api/suggestions/collection/status",
                 "/api/suggestions/collection/runs"):
        assert (await app_client.get(path)).status_code == 200, path


def test_scan_candle_basis_derived_from_scanner_run_time():
    class Row:
        research_metadata = {}
        scanner_run_id = 7

    in_session = dt.datetime(2026, 9, 29, 4, 51, tzinfo=dt.UTC)  # 10:21 IST
    after_close = dt.datetime(2026, 9, 29, 10, 35, tzinfo=dt.UTC)  # 16:05 IST
    assert an.scan_candle_basis(Row, {7: in_session}) == "INCLUDED_FORMING_DAILY_CANDLE"
    assert an.scan_candle_basis(Row, {7: after_close}) == "COMPLETED_DAILY_CANDLES"
    assert an.scan_candle_basis(Row, {}) == "UNKNOWN"


def test_rejection_reason_categories():
    assert an.reason_category("entry_high has non-tradable quality FALLBACK (price 1.0)") == "entry_high FALLBACK"
    assert an.reason_category("generation price STALE: tick 40s old") == "generation price STALE"
    assert an.reason_category("LONG target_1 102.5 must be above entry_high 103.0").startswith("invalid geometry")


async def test_stock_analysis_quote_timestamp_is_labelled(app_client):
    resp = await app_client.get("/api/stocks/NSE:RELIANCE-EQ/analysis")
    if resp.status_code == 422:
        pytest.skip("mock candidate rejected by filters")
    md = resp.json()["market_data"]
    assert md["as_of_basis"] in ("QUOTE_SNAPSHOT_RETRIEVAL_TIME", "SCAN_CLOSE_FALLBACK_NO_QUOTE")
    retrieved = dt.datetime.fromisoformat(md["as_of"].replace("Z", "+00:00"))
    assert abs((dt.datetime.now(dt.UTC) - retrieved).total_seconds()) < 120
