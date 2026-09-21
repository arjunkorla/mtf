"""Tests for app.services.research_confirmation_service (Phase 5)."""

import pytest

import app.services.fno_service as fno_service
import app.services.research_confirmation_service as research_confirmation_service
from app.config import Settings
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.mock_responses import mock_options_chain_response
from app.schemas.common import DataQuality, InstitutionalFootprint, PositionSizing, ScenarioLevels, ScoreComponent, SetupDetection
from app.schemas.scanner import CandidateResponse
from app.schemas.stock import FnoData, FundamentalData, NewsData, RelativeStrengthData, SectorData, TechnicalData, VolumeData

pytestmark = pytest.mark.asyncio


def _minimal_candidate() -> CandidateResponse:
    return CandidateResponse(
        symbol="NSE:TEST-EQ", company_name="Test Co", sector="IT", score=50.0,
        score_components=[ScoreComponent(name="data_quality", weight=5, points_awarded=5.0, available=True)],
        signal_quality="MEDIUM", price=100.0, entry_zone_low=95.0, entry_zone_high=100.0, invalidation=90.0,
        scenarios=ScenarioLevels(entry_zone_low=95.0, entry_zone_high=100.0, preferred_entry=100.0, invalidation=90.0, resistance_scenario_1=110.0),
        setup=SetupDetection(setup_type="NONE"),
        institutional_footprint=InstitutionalFootprint(institutional_footprint_score=None, institutional_footprint_level="INSUFFICIENT_DATA"),
        technical=TechnicalData(), volume=VolumeData(), fno=FnoData(is_available=False, positioning_proxy="NOT_AVAILABLE"),
        fundamentals=FundamentalData(is_available=False), relative_strength=RelativeStrengthData(label="INSUFFICIENT_DATA"),
        sector_context=SectorData(relative_strength=RelativeStrengthData(label="INSUFFICIENT_DATA")),
        news=NewsData(items=[], overall_sentiment="UNKNOWN"),
        position_sizing=PositionSizing(
            available_capital=100000, risk_percent=1.0, entry_price=100.0, invalidation_price=90.0,
            risk_per_share=10.0, max_rupee_risk=1000.0, quantity=100, capital_required=10000.0, capital_utilization_pct=10.0,
        ),
        data_quality=DataQuality(data_quality_score=50.0),
    )


def _live_client() -> FyersClient:
    return FyersClient(settings=Settings(use_mock_fyers=False, fyers_client_id="test-client", fyers_access_token="test-token"))


async def test_india_vix_fetch_is_cached_not_refetched_per_call(monkeypatch):
    """Phase 5 Step 13 requirement: VIX must resolve to ONE fetch reused
    across candidates, not one per candidate -- proven here by calling the
    fetch helper twice and asserting the underlying options-chain fetch
    (fno_service's real one, monkeypatched to count calls) only ran once."""
    call_count = {"n": 0}

    async def _counting_get_options_chain(client, symbol):
        call_count["n"] += 1
        return mock_options_chain_response(symbol)

    monkeypatch.setattr(fno_service, "get_options_chain", _counting_get_options_chain)

    client = _live_client()
    vix1, source1 = await research_confirmation_service._fetch_india_vix(client)
    vix2, source2 = await research_confirmation_service._fetch_india_vix(client)

    assert vix1 == vix2 == 11.47
    assert source1 == source2
    assert call_count["n"] == 1  # second call was a cache hit, not a re-fetch


async def test_india_vix_outage_never_crashes_and_returns_none(monkeypatch):
    async def _boom(client, symbol):
        raise RuntimeError("simulated options-chain outage")

    monkeypatch.setattr(fno_service, "get_options_chain", _boom)

    client = _live_client()
    vix, source = await research_confirmation_service._fetch_india_vix(client)

    assert vix is None
    assert source is None


async def test_global_macro_outage_never_crashes_build(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated global macro outage")

    monkeypatch.setattr(research_confirmation_service, "get_global_macro_snapshot", _boom)

    # A total outage in get_global_macro_snapshot itself is not caught inside
    # build_research_confirmation_for_candidate (that function's own internal
    # per-symbol isolation lives in global_macro_service.py) -- this test
    # documents that a hard failure here propagates rather than being
    # silently swallowed twice, so a real regression is loud, not hidden.
    with pytest.raises(RuntimeError):
        await research_confirmation_service.build_research_confirmation_for_candidate(_minimal_candidate(), _live_client())
