"""Phase B: read-only suggestion API. Suggestions are created through the
internal service (there is no public create endpoint); outcomes come from
controlled observations applied through the Phase A service. No FYERS."""

import datetime as dt

import pytest

from app.core.suggestion_constants import LevelQuality
from app.engines.suggestion_state_engine import Tick
from app.schemas.suggestion import LevelInput, SuggestionCreateRequest
from app.services import suggestion_service as svc

V = LevelQuality.VERIFIED_STRUCTURE.value
NOW = dt.datetime.now(dt.UTC).replace(microsecond=0)


def request(symbol: str, generated_at: dt.datetime, **overrides) -> SuggestionCreateRequest:
    levels = {
        "entry_low": LevelInput(price=100.0, quality=V), "entry_high": LevelInput(price=102.0, quality=V),
        "target_1": LevelInput(price=110.0, quality=V), "target_2": LevelInput(price=120.0, quality=V),
        "stop_loss": LevelInput(price=95.0, quality=V),
    }
    base = dict(
        scanner_type="MTF", market="NSE_EQ", symbol=symbol, instrument_type="EQUITY", direction="LONG",
        setup_type="PULLBACK", generated_at=generated_at, generation_market_price=101.0,
        generation_price_source="QUOTE", market_status="MARKET_OPEN_LIVE", data_quality="HIGH", levels=levels,
        evidence_snapshot={"rsi_14": 55.0, "provider_api_key": "must-not-leak", "nested": {"access_token": "x"}},
    )
    base.update(overrides)
    return SuggestionCreateRequest(**base)


async def make(db, symbol: str, prices: list[float] | None = None, age: dt.timedelta = dt.timedelta(hours=1)) -> int:
    gen = NOW - age
    result = await svc.create_suggestion(db, request(symbol, gen))
    sid = result.suggestion_id
    if prices:
        await svc.apply_observations(
            db, sid, [Tick(at=gen + dt.timedelta(minutes=i + 1), price=p) for i, p in enumerate(prices)]
        )
    return sid


async def test_list_defaults_to_last_7_days_without_deleting_history(app_client, db_session):
    old = await make(db_session, "NSE:OLD-EQ", age=dt.timedelta(days=10))
    new = await make(db_session, "NSE:NEW-EQ")

    body = (await app_client.get("/api/suggestions")).json()
    assert [i["id"] for i in body["items"]] == [new] and body["total"] == 1
    assert body["window"]["defaulted_to_last_7_days"] is True

    since = (NOW - dt.timedelta(days=30)).isoformat().replace("+00:00", "Z")
    body = (await app_client.get("/api/suggestions", params={"from": since})).json()
    assert {i["id"] for i in body["items"]} == {old, new} and body["window"]["defaulted_to_last_7_days"] is False
    assert (await app_client.get(f"/api/suggestions/{old}")).status_code == 200  # never deleted


async def test_pagination(app_client, db_session):
    ids = [await make(db_session, f"NSE:P{i}-EQ", age=dt.timedelta(hours=10 - i)) for i in range(5)]
    body = (await app_client.get("/api/suggestions", params={"limit": 2, "offset": 2})).json()
    assert body["total"] == 5 and body["limit"] == 2 and body["offset"] == 2
    newest_first = list(reversed(ids))
    assert [i["id"] for i in body["items"]] == newest_first[2:4]
    assert (await app_client.get("/api/suggestions", params={"limit": 501})).status_code == 422


async def test_status_outcome_symbol_direction_filters(app_client, db_session):
    waiting = await make(db_session, "NSE:W-EQ")
    stopped = await make(db_session, "NSE:S-EQ", [101.0, 94.0])
    winner = await make(db_session, "NSE:T-EQ", [101.0, 111.0, 121.0])

    def ids(resp):
        return {i["id"] for i in resp.json()["items"]}

    assert ids(await app_client.get("/api/suggestions", params={"status": "WAITING_ENTRY"})) == {waiting}
    assert ids(await app_client.get("/api/suggestions", params=[("status", "STOP_HIT"), ("status", "TARGET_2_HIT")])) == {stopped, winner}
    assert ids(await app_client.get("/api/suggestions", params={"outcome": "FAILED_STOP"})) == {stopped}
    assert ids(await app_client.get("/api/suggestions", params={"outcome": "success_target_2"})) == {winner}
    assert ids(await app_client.get("/api/suggestions", params={"symbol": "NSE:T-EQ"})) == {winner}
    assert ids(await app_client.get("/api/suggestions", params={"direction": "SHORT"})) == set()
    assert ids(await app_client.get("/api/suggestions", params={"scanner": "MTF", "market": "NSE_EQ"})) == {waiting, stopped, winner}


async def test_detail_is_auditable_and_redacts_secret_like_keys(app_client, db_session):
    sid = await make(db_session, "NSE:D-EQ", [101.0])
    body = (await app_client.get(f"/api/suggestions/{sid}")).json()
    for key in ("generated_at", "generation_market_price", "generation_price_source", "entry_low", "entry_high",
                "target_1", "target_2", "stop_loss", "level_quality", "status", "outcome", "entry_triggered_at",
                "entry_triggered_price", "max_favorable_excursion", "max_adverse_excursion", "ambiguous_bar",
                "data_quality", "market_status", "tracking_status", "reconciled_through", "evidence_snapshot"):
        assert key in body, key
    assert body["status"] == "ACTIVE" and body["entry_triggered_price"] == 101.0
    assert body["evidence_snapshot"]["rsi_14"] == 55.0
    assert body["evidence_snapshot"]["provider_api_key"] == "[REDACTED]"
    assert body["evidence_snapshot"]["nested"]["access_token"] == "[REDACTED]"
    assert body["provisional_live"] is None and "Research measurement only" in body["disclaimer"]
    assert (await app_client.get("/api/suggestions/999999")).status_code == 404


async def test_events_are_chronological_and_complete(app_client, db_session):
    sid = await make(db_session, "NSE:E-EQ", [101.0, 111.0, 94.0])
    events = (await app_client.get(f"/api/suggestions/{sid}/events")).json()
    assert [e["sequence"] for e in events] == sorted(e["sequence"] for e in events) == list(range(1, len(events) + 1))
    assert events[0]["event_type"] == "SUGGESTION_CREATED"
    stop = events[-1]
    assert stop["event_type"] == "STOP_HIT" and stop["from_status"] == "TARGET_1_HIT" and stop["to_status"] == "STOP_HIT"
    assert stop["threshold_price"] == 95.0 and stop["observed_market_price"] == 94.0
    for key in ("observed_at", "data_source", "observed_price_basis", "ambiguous_bar", "detail"):
        assert key in stop
    assert (await app_client.get("/api/suggestions/999999/events")).status_code == 404


async def test_performance_denominator_excludes_non_trades(app_client, db_session):
    await make(db_session, "NSE:WIN-EQ", [101.0, 111.0, 121.0])  # SUCCESS_TARGET_2
    await make(db_session, "NSE:LOSS-EQ", [101.0, 94.0])  # FAILED_STOP
    await make(db_session, "NSE:PART-EQ", [101.0, 111.0, 94.0])  # PARTIAL_SUCCESS
    await make(db_session, "NSE:INV-EQ", [94.0])  # INVALIDATED_BEFORE_ENTRY
    no_entry = await make(db_session, "NSE:NOE-EQ")
    row = await svc.get_suggestion(db_session, no_entry)
    await svc.apply_session_close(db_session, no_entry, row.entry_deadline_session_date, None,
                                  NOW, "CANDLE_D")  # NO_ENTRY
    expired = await make(db_session, "NSE:EXP-EQ", [101.0])
    row = await svc.get_suggestion(db_session, expired)
    await svc.apply_session_close(db_session, expired, row.holding_deadline_session_date, 104.0, NOW, "CANDLE_D")
    await make(db_session, "NSE:OPEN-EQ", [101.0])  # still ACTIVE
    await make(db_session, "NSE:WAIT-EQ")  # still WAITING

    body = (await app_client.get("/api/suggestions/performance")).json()
    assert body["total_suggestions"] == 8
    assert body["counts"]["no_entry"] == 1 and body["counts"]["invalidated"] == 1
    assert body["counts"]["waiting_entry"] == 1 and body["counts"]["active"] == 1
    assert body["counts"]["target_2_hit"] == 1 and body["counts"]["stop_hit"] == 2 and body["counts"]["expired"] == 1
    assert body["triggered_trades"] == 5  # win, loss, partial, expired, open
    assert body["completed_trades"] == body["sample_size"] == 4
    assert (body["wins"], body["losses"], body["partial_successes"], body["expired_without_target"]) == (1, 1, 1, 1)
    assert body["win_rate_pct"] == 25.0  # NO_ENTRY / INVALIDATED do not dilute or inflate it
    assert body["partial_success_rate_pct"] == 25.0 and body["loss_rate_pct"] == 25.0
    low, high = body["win_rate_95ci_pct"]
    assert low < 25.0 < high and high - low > 50  # a sample of 4 is visibly inconclusive
    assert body["sample_status"] == "REPORTED_WITH_SAMPLE_SIZE"
    assert body["methodology"]["minimum_sample_threshold"] is None
    text = str(body).upper()
    assert not any(claim in text for claim in ("PROFITABLE", "PROVEN", "HIGH WIN RATE"))


async def test_performance_with_no_trades_reports_empty_sample(app_client, db_session):
    await make(db_session, "NSE:ONLY-EQ")
    body = (await app_client.get("/api/suggestions/performance")).json()
    assert body["sample_size"] == 0 and body["win_rate_pct"] is None and body["win_rate_95ci_pct"] is None
    assert body["sample_status"] == "NO_COMPLETED_TRADES"


async def test_no_public_write_endpoints(app_client, db_session):
    sid = await make(db_session, "NSE:RO-EQ")
    assert (await app_client.post("/api/suggestions", json={})).status_code == 405
    assert (await app_client.put(f"/api/suggestions/{sid}", json={})).status_code == 405
    assert (await app_client.delete(f"/api/suggestions/{sid}")).status_code == 405


async def test_api_reads_never_call_fyers(app_client, db_session, monkeypatch):
    from app.integrations.fyers.fyers_client import FyersClient

    async def _forbidden(*args, **kwargs):
        raise AssertionError("suggestion API must not call FYERS")

    monkeypatch.setattr(FyersClient, "_send", _forbidden)
    sid = await make(db_session, "NSE:NF-EQ", [101.0])
    for path in ("/api/suggestions", f"/api/suggestions/{sid}", f"/api/suggestions/{sid}/events",
                 "/api/suggestions/performance", "/api/suggestions/tracker/status"):
        assert (await app_client.get(path)).status_code == 200, path


async def test_tracker_status_endpoint_reports_disabled_by_default(app_client):
    body = (await app_client.get("/api/suggestions/tracker/status")).json()
    assert body["enabled"] is False and body["state"] == "DISABLED"
    assert body["fyers_priority"] == "CRITICAL"


async def test_analysis_dataset_rows_use_snapshot_features_and_outcomes(app_client, db_session):
    sid = await make(db_session, "NSE:AN-EQ", [101.0, 111.0, 121.0], age=dt.timedelta(days=20))
    body = (await app_client.get("/api/suggestions/analysis-dataset")).json()  # no implicit 7-day window
    row = next(r for r in body["rows"] if r["id"] == sid)
    assert row["outcome"] == "SUCCESS_TARGET_2" and row["entry_triggered"] is True
    assert row["minutes_to_entry"] == 1.0 and row["minutes_entry_to_target_1"] == 1.0
    assert row["minutes_entry_to_target_2"] == 2.0 and row["minutes_entry_to_stop"] is None
    assert row["rsi_14"] is None  # not in this snapshot -> missing, never filled from elsewhere
    assert body["total"] == 1


async def test_scanner_response_score_and_ranking_unchanged_by_adapter(app_client, monkeypatch):
    """Scanner regression: same mock-mode scan with the Phase C adapter off
    and on (dry-run) -> identical candidates, scores and order; the adapter
    rejects every candidate because mock quotes are never a generation price."""
    from app.config import get_settings
    from app.services import mtf_suggestion_adapter as ad

    payload = {"available_capital": 100000, "risk_percent": 1, "max_positions": 5, "holding_period": "1-4 weeks",
               "symbols": ["NSE:RELIANCE-EQ", "NSE:INFY-EQ", "NSE:HDFCBANK-EQ"]}

    def strip(body):
        return [(c["symbol"], c["score"], c["entry_zone_low"], c["entry_zone_high"], c["invalidation"])
                for c in body["candidates"]]

    off = (await app_client.post("/api/scanner/run", json=payload)).json()
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_mtf_suggestion_adapter", True)
    on = (await app_client.post("/api/scanner/run", json=payload)).json()
    assert strip(on) == strip(off) and on["stocks_selected"] == off["stocks_selected"]

    last = ad.last_run()
    assert last["mode"] == "DRY_RUN" and last["scanner_run_id"] == on["run_id"] and last["persisted"] == 0
    assert all(any("MOCK_DATA_REJECTED" in r for r in res["rejection_reasons"]) for res in last["results"])
    body = (await app_client.get("/api/suggestions", params={"from": "2000-01-01T00:00:00Z"})).json()
    assert body["total"] == 0


@pytest.mark.parametrize("bad",["/api/suggestions/abc", "/api/suggestions/abc/events"])
async def test_non_integer_ids_are_rejected(app_client, bad):
    assert (await app_client.get(bad)).status_code == 422
