"""Integration tests for GET /api/scanner/{symbol}/research-confirmation
(Phase 5). Runs in USE_MOCK_FYERS=true mode via the app_client fixture."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_research_confirmation_returns_expected_top_level_shape(app_client):
    resp = await app_client.get("/api/scanner/NSE:RELIANCE-EQ/research-confirmation")
    assert resp.status_code == 200
    data = resp.json()

    assert data["symbol"] == "NSE:RELIANCE-EQ"
    assert data["label"] == "EXPERIMENTAL -- NOT PRODUCTION VALIDATED"
    assert "mtf_score" in data
    assert "research_confirmation_score" in data
    assert data["research_status"] in (
        "HIGH_CONFIRMATION", "SUPPORTIVE", "NEUTRAL", "CONFLICTING", "WEAK", "INSUFFICIENT_DATA",
    )
    assert data["corporate_event_context"]["status"] == "NOT_AVAILABLE"
    assert data["research_data_coverage"]["corporate_events"] is False
    assert "india_vix" in data["source_provenance"]
    assert "global_macro" in data["source_provenance"]


async def test_research_confirmation_unknown_symbol_returns_404(app_client):
    resp = await app_client.get("/api/scanner/NSE:NOTAREALSYMBOL-EQ/research-confirmation")
    assert resp.status_code == 404


async def test_research_confirmation_never_included_in_existing_scanner_contract(app_client):
    """Additive-only requirement: the existing /api/scanner/results contract
    must not gain any new required fields because of this feature."""
    scanner_resp = await app_client.post(
        "/api/scanner/run",
        json={"available_capital": 100000, "risk_percent": 1.0, "symbols": ["NSE:RELIANCE-EQ"]},
    )
    assert scanner_resp.status_code == 200
    candidate_keys = set(scanner_resp.json()["candidates"][0].keys()) if scanner_resp.json()["candidates"] else set()
    assert "research_confirmation_score" not in candidate_keys
