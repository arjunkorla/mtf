import pytest

from app.core.exceptions import FyersApiError

pytestmark = pytest.mark.asyncio


async def test_scanner_run_distinguishes_error_categories(app_client, monkeypatch):
    """Regression test for the calculation_error investigation: a stale/
    invalid FYERS symbol (HTTP 422 "Invalid symbol provided", confirmed live
    for the now-removed NSE:TATAMOTORS-EQ) and an actual bug in our own code
    must NOT be silently collapsed into the same "calculation_error" bucket.
    Uses two real, currently-configured universe symbols with simulated
    failures -- not tied to any specific symbol's real-world validity."""
    import app.services.scanner_service as scanner_service

    original_build_candidate = scanner_service.build_candidate
    invalid_symbol = "NSE:TMCV-EQ"
    buggy_symbol = "NSE:ADANIENT-EQ"

    async def _flaky_build_candidate(client, entry, context, settings, **kwargs):
        if entry.symbol == invalid_symbol:
            raise FyersApiError("FYERS API error on /history: HTTP 422", status_code=422)
        if entry.symbol == buggy_symbol:
            raise ZeroDivisionError("simulated bug in our own calculation code")
        return await original_build_candidate(client, entry, context, settings, **kwargs)

    monkeypatch.setattr(scanner_service, "build_candidate", _flaky_build_candidate)

    payload = {"available_capital": 100000, "risk_percent": 2, "max_positions": 5, "holding_period": "1-4 weeks"}
    resp = await app_client.post("/api/scanner/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()

    # both failures are tracked under their own distinct reason, not merged
    assert body["rejection_summary"].get("invalid_symbol") == 1
    assert body["rejection_summary"].get("calculation_error") == 1


async def test_scanner_run_breaks_score_ties_deterministically(app_client, monkeypatch):
    """Phase 5: an explicit tie-break (symbol, ascending) must decide equal
    scores, not incidental universe/insertion order -- otherwise a future
    change to iteration order (or parallelizing the per-symbol fetch loop)
    could silently reshuffle ranking for tied candidates."""
    import app.services.scanner_service as scanner_service

    original_build_candidate = scanner_service.build_candidate
    tied_symbols = {"NSE:HDFCBANK-EQ", "NSE:RELIANCE-EQ", "NSE:INFY-EQ"}

    async def _tied_score_build_candidate(client, entry, context, settings, **kwargs):
        candidate = await original_build_candidate(client, entry, context, settings, **kwargs)
        if entry.symbol in tied_symbols:
            candidate = candidate.model_copy(update={"score": 50.0})
        return candidate

    monkeypatch.setattr(scanner_service, "build_candidate", _tied_score_build_candidate)

    payload = {
        "available_capital": 100000, "risk_percent": 2, "max_positions": 5,
        "holding_period": "1-4 weeks",
        "symbols": ["NSE:HDFCBANK-EQ", "NSE:RELIANCE-EQ", "NSE:INFY-EQ"],  # deliberately not alphabetical
    }
    resp = await app_client.post("/api/scanner/run", json=payload)
    assert resp.status_code == 200
    symbols_in_order = [c["symbol"] for c in resp.json()["candidates"]]

    assert all(c == 50.0 for c in [cand["score"] for cand in resp.json()["candidates"]])
    assert symbols_in_order == sorted(symbols_in_order)


async def test_scanner_run_returns_ranked_candidates(app_client):
    payload = {
        "available_capital": 100000,
        "risk_percent": 2,
        "max_positions": 5,
        "holding_period": "1-4 weeks",
    }
    resp = await app_client.post("/api/scanner/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()

    assert body["status"] == "completed"
    assert body["stocks_analyzed"] > 0
    assert 0 < len(body["candidates"]) <= 10

    scores = [c["score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)

    for candidate in body["candidates"]:
        assert candidate["data_quality"]["data_quality_score"] >= 0
        assert candidate["position_sizing"]["available_capital"] == 100000
        assert candidate["institutional_footprint"]["institutional_footprint_level"] in (
            "STRONG", "MODERATE", "WEAK", "NEUTRAL", "INSUFFICIENT_DATA",
        )
        # Section 9: must never assert buying claims as fact.
        for ev in candidate["institutional_footprint"]["evidence"]:
            assert "institutions are buying" not in ev["detail"].lower()


async def test_scanner_run_default_scans_full_universe(app_client):
    """Omitting `symbols` entirely must retain the pre-existing behavior:
    the full configured universe, unchanged."""
    from app.data.universe import get_seed_universe

    payload = {"available_capital": 100000, "risk_percent": 2, "max_positions": 10, "holding_period": "1-4 weeks"}
    resp = await app_client.post("/api/scanner/run", json=payload)
    assert resp.status_code == 200
    assert resp.json()["stocks_analyzed"] == len(get_seed_universe())


async def test_scanner_run_with_symbols_scans_only_requested(app_client):
    requested = ["NSE:RELIANCE-EQ", "NSE:INFY-EQ", "NSE:HDFCBANK-EQ"]
    payload = {
        "available_capital": 100000, "risk_percent": 2, "max_positions": 5,
        "holding_period": "1-4 weeks", "symbols": requested,
    }
    resp = await app_client.post("/api/scanner/run", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["stocks_analyzed"] == 3
    assert {c["symbol"] for c in body["candidates"]} <= set(requested)


async def test_scanner_run_rejects_unknown_symbol(app_client):
    payload = {
        "available_capital": 100000, "risk_percent": 2, "max_positions": 5,
        "holding_period": "1-4 weeks", "symbols": ["NSE:NOTAREALSTOCK-EQ"],
    }
    resp = await app_client.post("/api/scanner/run", json=payload)
    assert resp.status_code == 422


async def test_scanner_run_rejects_empty_symbol_list(app_client):
    payload = {
        "available_capital": 100000, "risk_percent": 2, "max_positions": 5,
        "holding_period": "1-4 weeks", "symbols": [],
    }
    resp = await app_client.post("/api/scanner/run", json=payload)
    assert resp.status_code == 422


async def test_scanner_run_deduplicates_symbols(app_client):
    payload = {
        "available_capital": 100000, "risk_percent": 2, "max_positions": 5,
        "holding_period": "1-4 weeks",
        "symbols": ["NSE:RELIANCE-EQ", "NSE:RELIANCE-EQ", "NSE:INFY-EQ"],
    }
    resp = await app_client.post("/api/scanner/run", json=payload)
    assert resp.status_code == 200
    assert resp.json()["stocks_analyzed"] == 2


async def test_scanner_results_returns_latest_run(app_client):
    payload = {"available_capital": 50000, "risk_percent": 1.5, "max_positions": 3, "holding_period": "1-4 weeks"}
    run_resp = await app_client.post("/api/scanner/run", json=payload)
    run_id = run_resp.json()["run_id"]

    results_resp = await app_client.get("/api/scanner/results")
    assert results_resp.status_code == 200
    assert results_resp.json()["run_id"] == run_id

    by_id_resp = await app_client.get(f"/api/scanner/results?run_id={run_id}")
    assert by_id_resp.status_code == 200
    assert by_id_resp.json()["run_id"] == run_id


async def test_position_size_endpoint(app_client):
    resp = await app_client.post(
        "/api/position-size",
        json={"available_capital": 100000, "risk_percent": 2, "entry_price": 100, "invalidation_price": 95},
    )
    assert resp.status_code == 200
    sizing = resp.json()["position_sizing"]
    assert sizing["quantity"] == 400
    assert sizing["max_rupee_risk"] == 2000.0
