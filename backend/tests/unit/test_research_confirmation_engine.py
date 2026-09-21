"""Tests for app.engines.research_confirmation_engine (Phase 5). Builds
CandidateResponse/RealtimeConfirmationResponse fixtures directly rather than
running the full scanner pipeline, so these are deterministic unit tests of
the research-layer's own re-weighting/conflict-detection logic -- not a
re-test of scoring_engine.py or realtime_confirmation_service.py themselves.
"""

from app.core.constants import RESEARCH_WEIGHTS
from app.engines.research_confirmation_engine import build_india_vix_context, build_research_confirmation
from app.schemas.common import (
    DataQuality,
    EvidenceItem,
    InstitutionalFootprint,
    PositionSizing,
    ScenarioLevels,
    ScoreComponent,
    SetupDetection,
)
from app.schemas.confirmation import (
    DepthConfirmationData,
    FuturesConfirmationData,
    PersistenceData,
    PriceConfirmationData,
    RealtimeConfirmationResponse,
    SpreadConditionData,
    VolumeConfirmationData,
    VwapConfirmationData,
)
from app.schemas.research import GlobalMacroContext, MacroContextItem
from app.schemas.scanner import CandidateResponse
from app.schemas.stock import FnoData, FundamentalData, NewsData, RelativeStrengthData, SectorData, TechnicalData, VolumeData

import datetime as dt


def _component(name, weight, points_awarded=None, available=True, evidence=None):
    return ScoreComponent(
        name=name, weight=weight, points_awarded=points_awarded, available=available,
        reason_unavailable=None if available else "unavailable in fixture",
        evidence=evidence or [],
    )


def _make_candidate(score_components=None, **overrides) -> CandidateResponse:
    defaults = dict(
        symbol="NSE:TEST-EQ",
        company_name="Test Co",
        sector="IT",
        score=50.0,
        score_components=score_components
        or [
            _component("technical_structure", 20, 15.0, evidence=[EvidenceItem(label="Trend structure", detail="UPTREND", is_positive=True)]),
            _component("volume_accumulation", 20, 10.0),
            _component("relative_strength", 15, 11.25, evidence=[EvidenceItem(label="RS", detail="OUTPERFORM", is_positive=True)]),
            _component("fno_positioning", 15, 7.5, evidence=[EvidenceItem(label="FnO", detail="NEUTRAL")]),
            _component("fundamentals", 10, available=False),
            _component("catalyst_news", 10, 5.0),
            _component("market_sector", 5, 2.5),
            _component("data_quality", 5, 4.25),
        ],
        signal_quality="MEDIUM",
        price=100.0,
        entry_zone_low=95.0,
        entry_zone_high=100.0,
        invalidation=90.0,
        scenarios=ScenarioLevels(entry_zone_low=95.0, entry_zone_high=100.0, preferred_entry=100.0, invalidation=90.0, resistance_scenario_1=110.0),
        setup=SetupDetection(setup_type="NONE"),
        institutional_footprint=InstitutionalFootprint(institutional_footprint_score=60.0, institutional_footprint_level="MODERATE"),
        technical=TechnicalData(trend_structure="UPTREND", breakout_status="NO_BREAKOUT"),
        volume=VolumeData(volume_ratio=1.0),
        fno=FnoData(is_available=True, positioning_proxy="NEUTRAL"),
        fundamentals=FundamentalData(is_available=False),
        relative_strength=RelativeStrengthData(label="OUTPERFORM", vs_nifty_pct_20d=3.0),
        sector_context=SectorData(sector_name="IT", sector_strength_label="STRONG", market_regime="RISK_ON", relative_strength=RelativeStrengthData(label="OUTPERFORM")),
        news=NewsData(items=[], overall_sentiment="UNKNOWN"),
        position_sizing=PositionSizing(
            available_capital=100000, risk_percent=1.0, entry_price=100.0, invalidation_price=90.0,
            risk_per_share=10.0, max_rupee_risk=1000.0, quantity=100, capital_required=10000.0, capital_utilization_pct=10.0,
        ),
        data_quality=DataQuality(data_quality_score=85.0, missing_data=["fundamentals"]),
    )
    defaults.update(overrides)
    return CandidateResponse(**defaults)


def _realtime(status="SUPPORTIVE", score=70.0):
    return RealtimeConfirmationResponse(
        symbol="NSE:TEST-EQ", timestamp=dt.datetime.now(dt.UTC), freshness="LIVE", market_status="MARKET_OPEN_LIVE",
        confirmation_status=status, confirmation_score=score, data_quality="HIGH",
        price_confirmation=PriceConfirmationData(status="INSIDE_ENTRY_ZONE", breakout_relation="NO_BREAKOUT_LEVEL", entry_zone_low=95, entry_zone_high=100, invalidation=90),
        volume_confirmation=VolumeConfirmationData(status="NORMAL"),
        vwap_confirmation=VwapConfirmationData(status="UNAVAILABLE"),
        depth_confirmation=DepthConfirmationData(status="BALANCED"),
        spread_condition=SpreadConditionData(status="HEALTHY"),
        futures_confirmation=FuturesConfirmationData(status="FLAT"),
        persistence=PersistenceData(status="INSUFFICIENT_OBSERVATIONS", observation_count=1, window=5),
    )


def _empty_macro(sector="IT", sentiment="RISK_ON"):
    return GlobalMacroContext(risk_sentiment=sentiment, broad_instruments=[], sector_specific_notes=[], source="Yahoo Finance (unofficial API)")


def test_never_mutates_the_input_candidate_or_its_score():
    candidate = _make_candidate(score=42.5)
    original_score = candidate.score
    original_component_count = len(candidate.score_components)

    result = build_research_confirmation(candidate, _realtime(), _empty_macro(), build_india_vix_context(None, None, None))

    assert candidate.score == original_score
    assert len(candidate.score_components) == original_component_count
    assert result.mtf_score == original_score


def test_reuses_existing_score_component_fractions_without_recomputation():
    candidate = _make_candidate()
    result = build_research_confirmation(candidate, _realtime(), _empty_macro(), build_india_vix_context(None, None, None))

    tech_rs = next(c for c in result.component_scores if c.name == "technical_and_relative_strength")
    # technical frac = 15/20 = 0.75, rs frac = 11.25/15 = 0.75 -> combined 0.75
    assert tech_rs.points_awarded == round(0.75 * RESEARCH_WEIGHTS["technical_and_relative_strength"], 2)


def test_missing_technical_and_rs_marks_component_unavailable_and_renormalizes():
    components = [
        _component("technical_structure", 20, available=False),
        _component("relative_strength", 15, available=False),
        _component("data_quality", 5, 5.0),
    ]
    candidate = _make_candidate(score_components=components)
    result = build_research_confirmation(candidate, None, _empty_macro(), build_india_vix_context(None, None, None))

    tech_rs = next(c for c in result.component_scores if c.name == "technical_and_relative_strength")
    assert tech_rs.available is False
    assert tech_rs.points_awarded is None
    # Score must still compute from whatever WAS available, never fabricated as 0.
    assert result.research_confirmation_score is not None


def test_corporate_events_component_is_always_unavailable():
    candidate = _make_candidate()
    result = build_research_confirmation(candidate, _realtime(), _empty_macro(), build_india_vix_context(None, None, None))
    corp = next(c for c in result.component_scores if c.name == "corporate_events")
    assert corp.available is False
    assert "NOT_AVAILABLE" in corp.reason_unavailable
    assert result.corporate_event_context.status == "NOT_AVAILABLE"
    assert "corporate_events" in result.missing_data
    assert result.research_data_coverage["corporate_events"] is False


def test_everything_unavailable_yields_insufficient_data_not_a_fabricated_zero():
    components = [_component(name, weight, available=False) for name, weight in RESEARCH_WEIGHTS.items() if name != "corporate_events"]
    candidate = _make_candidate(
        score_components=[_component("technical_structure", 20, available=False), _component("relative_strength", 15, available=False)],
        institutional_footprint=InstitutionalFootprint(institutional_footprint_score=None, institutional_footprint_level="INSUFFICIENT_DATA"),
        fno=FnoData(is_available=False, positioning_proxy="NOT_AVAILABLE"),
        sector_context=SectorData(sector_name=None, sector_strength_label=None, market_regime=None, relative_strength=RelativeStrengthData(label="INSUFFICIENT_DATA")),
        data_quality=DataQuality(data_quality_score=0.0),
    )
    result = build_research_confirmation(candidate, None, GlobalMacroContext(risk_sentiment="INSUFFICIENT_DATA", source="n/a"), build_india_vix_context(None, None, None))

    # data_quality itself is always computed (candidate.data_quality always exists),
    # so it alone keeps the score from being None -- but nothing is fabricated for
    # the genuinely-unavailable components.
    unavailable_names = {c.name for c in result.component_scores if not c.available}
    assert "corporate_events" in unavailable_names
    assert "technical_and_relative_strength" in unavailable_names
    assert "institutional_footprint" in unavailable_names
    assert "futures_options_positioning" in unavailable_names
    assert "live_confirmation" in unavailable_names


def test_conflict_high_mtf_score_with_contradictory_live_confirmation():
    candidate = _make_candidate(score=75.0)
    realtime = _realtime(status="CONTRADICTORY", score=None)
    result = build_research_confirmation(candidate, realtime, _empty_macro(), build_india_vix_context(None, None, None))

    assert "HIGH_MTF_SCORE_NEGATIVE_LIVE_CONFIRMATION" in result.conflicting_signals
    assert result.research_status == "CONFLICTING"


def test_conflict_forces_conflicting_status_even_when_score_would_otherwise_be_high():
    """Explicit requirement: contradictions are never hidden to make the
    score look clean, regardless of how high the numeric score is."""
    components = [
        _component("technical_structure", 20, 20.0, evidence=[EvidenceItem(label="Trend structure", detail="STRONG_UPTREND, breakout status BREAKOUT", is_positive=True)]),
        _component("relative_strength", 15, 15.0),
        _component("fno_positioning", 15, 15.0),
        _component("catalyst_news", 10, 10.0),
        _component("market_sector", 5, 5.0),
        _component("data_quality", 5, 5.0),
    ]
    candidate = _make_candidate(
        score=90.0, score_components=components,
        technical=TechnicalData(trend_structure="STRONG_UPTREND", breakout_status="BREAKOUT"),
        fno=FnoData(is_available=True, positioning_proxy="SHORT_BUILDUP_PROXY"),
    )
    result = build_research_confirmation(candidate, _realtime(), _empty_macro(), build_india_vix_context(None, None, None))

    assert "PRICE_BREAKOUT_SHORT_BUILDUP" in result.conflicting_signals
    assert result.research_status == "CONFLICTING"
    assert result.research_confirmation_score is not None and result.research_confirmation_score > 60


def test_supporting_signals_when_technical_and_sector_align():
    candidate = _make_candidate(sector_context=SectorData(sector_name="IT", sector_strength_label="STRONG", market_regime="RISK_ON", relative_strength=RelativeStrengthData(label="OUTPERFORM")))
    result = build_research_confirmation(candidate, _realtime(status="SUPPORTIVE", score=80.0), _empty_macro(), build_india_vix_context(None, None, None))

    assert "TECHNICAL_AND_SECTOR_ALIGNED" in result.supporting_signals


def test_futures_unavailable_marks_component_unavailable_not_neutral():
    components = [
        _component("technical_structure", 20, 15.0),
        _component("relative_strength", 15, 11.25),
        _component("fno_positioning", 15, available=False),
        _component("catalyst_news", 10, 5.0),
        _component("market_sector", 5, 2.5),
        _component("data_quality", 5, 4.25),
    ]
    candidate = _make_candidate(score_components=components, fno=FnoData(is_available=False, positioning_proxy="NOT_AVAILABLE"))
    result = build_research_confirmation(candidate, _realtime(), _empty_macro(), build_india_vix_context(None, None, None))

    futures = next(c for c in result.component_scores if c.name == "futures_options_positioning")
    assert futures.available is False
    assert futures.points_awarded is None


def test_news_unavailable_marks_catalyst_component_unavailable():
    components = [
        _component("technical_structure", 20, 15.0),
        _component("relative_strength", 15, 11.25),
        _component("fno_positioning", 15, 7.5),
        _component("catalyst_news", 10, available=False),
        _component("market_sector", 5, 2.5),
        _component("data_quality", 5, 4.25),
    ]
    candidate = _make_candidate(score_components=components, news=NewsData(items=[], overall_sentiment="UNKNOWN"))
    result = build_research_confirmation(candidate, _realtime(), _empty_macro(), build_india_vix_context(None, None, None))

    news_component = next(c for c in result.component_scores if c.name == "catalyst_news")
    assert news_component.available is False
    assert "news" in result.missing_data or result.research_data_coverage["news"] is False


def test_all_supportive_evidence_yields_high_confirmation_status():
    components = [
        _component("technical_structure", 20, 20.0, evidence=[EvidenceItem(label="Trend structure", detail="STRONG_UPTREND, breakout status BREAKOUT", is_positive=True)]),
        _component("relative_strength", 15, 15.0),
        _component("fno_positioning", 15, 15.0),
        _component("catalyst_news", 10, 10.0),
        _component("market_sector", 5, 5.0),
        _component("data_quality", 5, 5.0),
    ]
    candidate = _make_candidate(
        score=90.0, score_components=components,
        technical=TechnicalData(trend_structure="STRONG_UPTREND", breakout_status="BREAKOUT"),
        fno=FnoData(is_available=True, positioning_proxy="LONG_BUILDUP_PROXY"),
        institutional_footprint=InstitutionalFootprint(institutional_footprint_score=85.0, institutional_footprint_level="STRONG"),
        sector_context=SectorData(sector_name="IT", sector_strength_label="STRONG", market_regime="RISK_ON", relative_strength=RelativeStrengthData(label="OUTPERFORM")),
    )
    result = build_research_confirmation(candidate, _realtime(status="STRONGLY_SUPPORTIVE", score=90.0), _empty_macro(), build_india_vix_context(11.0, dt.datetime.now(dt.UTC), "test"))

    assert result.conflicting_signals == []
    assert result.research_status == "HIGH_CONFIRMATION"
    assert len(result.supporting_signals) >= 1


def test_source_provenance_is_retained_for_every_research_source():
    candidate = _make_candidate()
    macro = GlobalMacroContext(
        risk_sentiment="RISK_ON",
        broad_instruments=[MacroContextItem(
            label="S&P 500", symbol="^GSPC", value=100.0, change_pct=1.0, as_of=dt.datetime.now(dt.UTC),
            session_state="LIVE_SESSION", affected_dimension="Broad risk sentiment", interpretation="context",
            confidence="LOW", source="Yahoo Finance (unofficial API)",
        )],
        sector_specific_notes=[], source="Yahoo Finance (unofficial API)",
    )
    result = build_research_confirmation(candidate, _realtime(), macro, build_india_vix_context(11.0, dt.datetime.now(dt.UTC), "FYERS options-chain"))

    assert "Yahoo Finance" in result.source_provenance["global_macro"]
    assert "FYERS" in result.source_provenance["india_vix"]
    assert result.source_provenance["corporate_events"].startswith("N/A")
    assert "scoring_engine.py" in result.source_provenance["mtf_score"]


def test_india_vix_never_appears_as_a_weighted_score_component():
    """Explicit design decision: VIX affects risk_signals/confidence only,
    never the numeric research_confirmation_score."""
    candidate = _make_candidate()
    result = build_research_confirmation(candidate, _realtime(), _empty_macro(), build_india_vix_context(35.0, dt.datetime.now(dt.UTC), "test"))

    component_names = {c.name for c in result.component_scores}
    assert "india_vix" not in component_names
    assert not any("vix" in name.lower() for name in component_names)
    assert "INDIA_VIX_HIGH" in result.risk_signals
