from app.core.constants import MtfLeverageStatus
from app.engines.momentum_ranking_engine import build_reason_qualified, compute_momentum_rank
from app.schemas.common import DataQuality, EvidenceItem, InstitutionalFootprint, PositionSizing, ScenarioLevels, SetupDetection
from app.schemas.mtf_leverage import MtfLeverageResult
from app.schemas.scanner import CandidateResponse
from app.schemas.stock import (
    FnoData,
    FundamentalData,
    NewsData,
    RelativeStrengthData,
    SectorData,
    TechnicalData,
    VolumeData,
)


def _candidate(
    rsi_14=62.0,
    breakout_status="BREAKOUT",
    volume_ratio=2.2,
    rs_label="OUTPERFORM",
    footprint_score=75.0,
    delivery_evidence=True,
) -> CandidateResponse:
    footprint_evidence = []
    if delivery_evidence:
        footprint_evidence.append(
            EvidenceItem(label="Delivery behaviour proxy", detail="60% delivery", value=60.0, is_positive=True)
        )
    return CandidateResponse(
        symbol="NSE:RELIANCE-EQ",
        company_name="Reliance Industries Ltd",
        sector="Energy",
        score=70.0,
        score_components=[],
        signal_quality="HIGH",
        price=2951.2,
        entry_zone_low=2900.0,
        entry_zone_high=2960.0,
        invalidation=2850.0,
        scenarios=ScenarioLevels(
            entry_zone_low=2900.0, entry_zone_high=2960.0, preferred_entry=2930.0,
            invalidation=2850.0, resistance_scenario_1=3050.0,
        ),
        setup=SetupDetection(setup_type="BREAKOUT"),
        institutional_footprint=InstitutionalFootprint(
            institutional_footprint_score=footprint_score,
            institutional_footprint_level="STRONG" if footprint_score and footprint_score >= 70 else "MODERATE",
            evidence=footprint_evidence,
        ),
        technical=TechnicalData(rsi_14=rsi_14, breakout_status=breakout_status),
        volume=VolumeData(volume_ratio=volume_ratio),
        fno=FnoData(is_available=False, positioning_proxy="NOT_AVAILABLE"),
        fundamentals=FundamentalData(is_available=False),
        relative_strength=RelativeStrengthData(label=rs_label, vs_nifty_pct_20d=5.0),
        sector_context=SectorData(relative_strength=RelativeStrengthData(label=rs_label)),
        news=NewsData(),
        position_sizing=PositionSizing(
            available_capital=100000.0, risk_percent=2.0, entry_price=2930.0, invalidation_price=2850.0,
            risk_per_share=80.0, max_rupee_risk=2000.0, quantity=25, capital_required=73250.0,
            capital_utilization_pct=73.25,
        ),
        data_quality=DataQuality(data_quality_score=90.0),
    )


def _verified_leverage(leverage=4.0) -> MtfLeverageResult:
    return MtfLeverageResult(mtf_status=MtfLeverageStatus.VERIFIED.value, required_margin_pct=25.0, effective_leverage=leverage)


def _unverified_leverage() -> MtfLeverageResult:
    return MtfLeverageResult(mtf_status=MtfLeverageStatus.UNVERIFIED.value, reason_unverified="No margin data")


def test_full_evidence_produces_a_score_and_all_components_present():
    candidate = _candidate()
    score, components = compute_momentum_rank(candidate, _verified_leverage(), 3.0, 6.0, 12.0)
    assert score is not None
    assert 0 <= score <= 100
    names = {c.name for c in components}
    assert names == {
        "institutional_footprint", "bulk_block_deal_evidence", "volume_and_delivery", "technical_momentum",
        "breakout_structure", "relative_strength", "liquidity", "mtf_characteristics",
    }


def test_bulk_block_deal_never_awards_points():
    candidate = _candidate()
    _, components = compute_momentum_rank(candidate, _verified_leverage(), 3.0, 6.0, 12.0)
    bulk_block = next(c for c in components if c.name == "bulk_block_deal_evidence")
    assert bulk_block.available is False
    assert bulk_block.points_awarded is None


def test_liquidity_always_unavailable_never_fabricated():
    candidate = _candidate()
    _, components = compute_momentum_rank(candidate, _verified_leverage(), 3.0, 6.0, 12.0)
    liquidity = next(c for c in components if c.name == "liquidity")
    assert liquidity.available is False


def test_unverified_leverage_excludes_mtf_component_but_still_scores():
    candidate = _candidate()
    score, components = compute_momentum_rank(candidate, _unverified_leverage(), 3.0, 6.0, 12.0)
    mtf_component = next(c for c in components if c.name == "mtf_characteristics")
    assert mtf_component.available is False
    assert score is not None  # other components still carry the score


def test_insufficient_components_returns_none_score():
    sparse = _candidate(
        rsi_14=None, breakout_status="INSUFFICIENT_DATA", volume_ratio=None,
        rs_label="INSUFFICIENT_DATA", footprint_score=None, delivery_evidence=False,
    )
    score, components = compute_momentum_rank(sparse, _unverified_leverage(), None, None, None)
    assert score is None


def test_build_reason_qualified_names_strong_components():
    candidate = _candidate()
    _, components = compute_momentum_rank(candidate, _verified_leverage(), 3.0, 6.0, 12.0)
    reason = build_reason_qualified(components)
    assert "Supported by" in reason or "no single component" in reason
