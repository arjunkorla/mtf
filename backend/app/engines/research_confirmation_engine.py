"""Research Confirmation Engine (Phase 5) -- an EXPERIMENTAL, separate
evidence-aggregation layer beside the existing MTF scanner.

CRITICAL: this module never imports scoring_engine.py or scanner_service.py,
and nothing here can change candidate ranking or selection. It only READS an
already-computed CandidateResponse (and, where available, an already-
computed RealtimeConfirmationResponse) plus the newly verified research
sources (India VIX, global macro) and re-weights that SAME evidence under a
separate, clearly-labeled experimental score.

--- Double-counting analysis (Phase 5 Step 6, done BEFORE picking weights) ---

Several "new" research dimensions are not actually independent of evidence
the production score (and its own institutional_footprint_engine.py) already
folds in. Treating them as full, separate weights would silently double- (or
triple-) count the same underlying observation:

  - Technical trend + relative strength: both are price-action-derived and
    positively correlated in trending markets. Combined into ONE bucket
    (technical_and_relative_strength, 20) with an internal 60/40 split,
    instead of two independent ~20-point buckets.
  - Volume expansion / accumulation + institutional footprint: institutional
    _footprint_engine.py's score is ALREADY an average of volume-expansion,
    price-volume-behaviour, accumulation, relative-strength, F&O, and
    delivery proxies. Giving institutional_footprint a full independent
    weight on top of separately-weighted volume/RS/F&O buckets would count
    the same volume/RS/F&O evidence 2-3x. Fix: institutional_footprint gets
    a REDUCED weight (15, not ~25+) specifically because of this overlap --
    it's kept as its own bucket for its own composite-proxy narrative, not
    dropped, but deliberately not treated as fully independent.
  - Futures OI + institutional proxy: institutional_footprint's own
    `_fno_proxy` already scores the same futures price/OI pattern. Same
    fix as above -- futures_options_positioning (12) is its own bucket for
    the specific LONG/SHORT-buildup + PCR narrative; institutional_footprint
    is down-weighted rather than this bucket being dropped.
  - Live price confirmation + technical breakout: the Real-Time Confirmation
    Engine's price/breakout-relation check is a same-day echo of the same
    daily breakout_status the technical bucket already scores. Fix:
    live_confirmation gets a reduced weight (10, not ~20+), justified as
    "does today's tape corroborate the multi-week setup" rather than an
    independent technical read.
  - Market regime + global equity sentiment: NIFTY trend structure (existing
    market_sector component) and global risk-on/risk-off sentiment (new)
    both describe "is the broader tape supportive." Combined into ONE
    bucket (market_regime_and_global_sentiment, 12) rather than two.

India VIX is deliberately NOT a weighted component at all (Phase 5 Step 5):
it affects risk_signals/confidence framing only, never the bullish/bearish
number -- seeing HIGH vix elsewhere in the response is not "missing 12
points," it's a risk flag layered on top of whatever the score already says.

Corporate events get a placeholder bucket (weight 8) that is ALWAYS
unavailable today (no verified free source exists -- see
CorporateEventContext) and is excluded/re-normalized exactly like any other
missing component, never fabricated as neutral/zero.
"""

import datetime as dt

from app.core.constants import GlobalRiskSentiment, RESEARCH_WEIGHTS, ResearchStatus
from app.engines.india_vix_engine import classify_vix_regime
from app.engines.sector_participation_engine import classify_sector_participation_from_deltas
from app.schemas.confirmation import RealtimeConfirmationResponse
from app.schemas.research import (
    CorporateEventContext,
    GlobalMacroContext,
    IndiaVixContext,
    ResearchComponentScore,
    ResearchConfirmation,
)
from app.schemas.scanner import CandidateResponse

# confirmation_status -> fraction, used only when realtime.confirmation_score
# itself is None (the score is preferred when present -- it's already
# re-normalized across whichever of price/volume/vwap/depth/futures/
# persistence were available).
_CONFIRMATION_STATUS_FRACTION = {
    "STRONGLY_SUPPORTIVE": 1.0,
    "SUPPORTIVE": 0.75,
    "NEUTRAL": 0.5,
    "CONTRADICTORY": 0.0,
}

_MARKET_REGIME_FRACTION = {"RISK_ON": 1.0, "NEUTRAL": 0.5, "RISK_OFF": 0.0}
_GLOBAL_SENTIMENT_FRACTION = {
    GlobalRiskSentiment.RISK_ON.value: 1.0,
    GlobalRiskSentiment.MIXED.value: 0.5,
    GlobalRiskSentiment.RISK_OFF.value: 0.0,
}


def _score_component_by_name(candidate: CandidateResponse, name: str):
    return next((c for c in candidate.score_components if c.name == name), None)


def _existing_component_evidence(candidate: CandidateResponse, name: str) -> list:
    component = _score_component_by_name(candidate, name)
    return list(component.evidence) if component is not None else []


def _existing_component_fraction(candidate: CandidateResponse, name: str) -> float | None:
    """Reuses a fraction the PRODUCTION score already computed
    (points_awarded/weight) -- never recalculated here, per the
    "don't duplicate CandidateResponse calculations" requirement."""
    component = _score_component_by_name(candidate, name)
    if component is None or not component.available or component.points_awarded is None or component.weight == 0:
        return None
    return component.points_awarded / component.weight


def _build_technical_and_rs_component(candidate: CandidateResponse) -> ResearchComponentScore:
    weight = RESEARCH_WEIGHTS["technical_and_relative_strength"]
    tech_frac = _existing_component_fraction(candidate, "technical_structure")
    rs_frac = _existing_component_fraction(candidate, "relative_strength")

    if tech_frac is None and rs_frac is None:
        return ResearchComponentScore(
            name="technical_and_relative_strength", weight=weight, available=False,
            reason_unavailable="Neither technical structure nor relative strength was available on the underlying candidate",
        )

    if tech_frac is not None and rs_frac is not None:
        frac = 0.6 * tech_frac + 0.4 * rs_frac
    else:
        frac = tech_frac if tech_frac is not None else rs_frac

    return ResearchComponentScore(
        name="technical_and_relative_strength", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=_existing_component_evidence(candidate, "technical_structure") + _existing_component_evidence(candidate, "relative_strength"),
    )


def _build_institutional_footprint_component(candidate: CandidateResponse) -> ResearchComponentScore:
    weight = RESEARCH_WEIGHTS["institutional_footprint"]
    fp = candidate.institutional_footprint
    if fp.institutional_footprint_score is None:
        return ResearchComponentScore(
            name="institutional_footprint", weight=weight, available=False,
            reason_unavailable="Fewer than the minimum number of institutional-footprint proxies were available",
        )
    frac = fp.institutional_footprint_score / 100.0
    return ResearchComponentScore(
        name="institutional_footprint", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=fp.evidence,
    )


def _build_fno_component(candidate: CandidateResponse) -> ResearchComponentScore:
    weight = RESEARCH_WEIGHTS["futures_options_positioning"]
    frac = _existing_component_fraction(candidate, "fno_positioning")
    if frac is None:
        return ResearchComponentScore(
            name="futures_options_positioning", weight=weight, available=False,
            reason_unavailable="Not an F&O stock, or futures/options data unavailable",
        )
    return ResearchComponentScore(
        name="futures_options_positioning", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=_existing_component_evidence(candidate, "fno_positioning"),
    )


def _build_live_confirmation_component(realtime: RealtimeConfirmationResponse | None) -> ResearchComponentScore:
    weight = RESEARCH_WEIGHTS["live_confirmation"]
    if realtime is None or realtime.confirmation_status == "INSUFFICIENT_DATA":
        return ResearchComponentScore(
            name="live_confirmation", weight=weight, available=False,
            reason_unavailable="Real-time confirmation unavailable (market closed, stale feed, or insufficient live data)",
        )
    frac = (
        realtime.confirmation_score / 100.0
        if realtime.confirmation_score is not None
        else _CONFIRMATION_STATUS_FRACTION.get(realtime.confirmation_status)
    )
    if frac is None:
        return ResearchComponentScore(
            name="live_confirmation", weight=weight, available=False,
            reason_unavailable=f"Unrecognized confirmation status: {realtime.confirmation_status}",
        )
    return ResearchComponentScore(
        name="live_confirmation", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=realtime.evidence,
    )


def _build_regime_and_sentiment_component(candidate: CandidateResponse, macro: GlobalMacroContext) -> ResearchComponentScore:
    weight = RESEARCH_WEIGHTS["market_regime_and_global_sentiment"]
    regime_frac = _MARKET_REGIME_FRACTION.get(candidate.sector_context.market_regime or "")
    sentiment_frac = _GLOBAL_SENTIMENT_FRACTION.get(macro.risk_sentiment)

    if regime_frac is None and sentiment_frac is None:
        return ResearchComponentScore(
            name="market_regime_and_global_sentiment", weight=weight, available=False,
            reason_unavailable="Neither NIFTY market regime nor global equity risk sentiment was available",
        )
    if regime_frac is not None and sentiment_frac is not None:
        frac = 0.7 * regime_frac + 0.3 * sentiment_frac
    else:
        frac = regime_frac if regime_frac is not None else sentiment_frac

    return ResearchComponentScore(
        name="market_regime_and_global_sentiment", weight=weight, points_awarded=round(frac * weight, 2), available=True,
    )


def _build_sector_context_component(candidate: CandidateResponse) -> ResearchComponentScore:
    weight = RESEARCH_WEIGHTS["sector_context"]
    frac = _existing_component_fraction(candidate, "market_sector")
    if frac is None:
        return ResearchComponentScore(
            name="sector_context", weight=weight, available=False,
            reason_unavailable="Sector strength unavailable (no sector index mapping or insufficient history)",
        )
    return ResearchComponentScore(name="sector_context", weight=weight, points_awarded=round(frac * weight, 2), available=True)


def _build_catalyst_news_component(candidate: CandidateResponse) -> ResearchComponentScore:
    weight = RESEARCH_WEIGHTS["catalyst_news"]
    component = _score_component_by_name(candidate, "catalyst_news")
    if component is None or not component.available or component.points_awarded is None:
        return ResearchComponentScore(
            name="catalyst_news", weight=weight, available=False,
            reason_unavailable="No recent news/catalyst data available",
        )
    frac = component.points_awarded / component.weight if component.weight else 0.5
    return ResearchComponentScore(name="catalyst_news", weight=weight, points_awarded=round(frac * weight, 2), available=True)


def _build_corporate_events_component() -> ResearchComponentScore:
    weight = RESEARCH_WEIGHTS["corporate_events"]
    return ResearchComponentScore(
        name="corporate_events", weight=weight, available=False,
        reason_unavailable="NOT_AVAILABLE -- no verified free/no-auth NSE corporate-events source exists (see CorporateEventContext)",
    )


def _build_data_quality_component(candidate: CandidateResponse) -> ResearchComponentScore:
    weight = RESEARCH_WEIGHTS["data_quality"]
    frac = candidate.data_quality.data_quality_score / 100.0
    return ResearchComponentScore(name="data_quality", weight=weight, points_awarded=round(frac * weight, 2), available=True)


def build_india_vix_context(vix: float | None, as_of: dt.datetime | None, source: str | None) -> IndiaVixContext:
    regime = classify_vix_regime(vix)
    notes = {
        "LOW_VOLATILITY": "Below the low-volatility threshold -- calm regime context, not a directional signal.",
        "NORMAL": "Within the typical India VIX range -- no elevated risk-context flag.",
        "ELEVATED": "Above the elevated threshold -- treat position sizing/confidence conservatively; not a sell signal by itself.",
        "HIGH": "Above the high threshold -- material market-wide risk context; treat any single setup with added caution.",
        "INSUFFICIENT_DATA": "India VIX unavailable this run.",
    }
    return IndiaVixContext(value=vix, regime=regime, as_of=as_of, source=source, note=notes[regime])


def _detect_conflicts(candidate: CandidateResponse, realtime: RealtimeConfirmationResponse | None, macro: GlobalMacroContext) -> list[str]:
    conflicts: list[str] = []
    tech_frac = _existing_component_fraction(candidate, "technical_structure")
    bullish_technical = tech_frac is not None and tech_frac >= 0.6

    if bullish_technical and candidate.sector_context.sector_strength_label == "WEAK":
        conflicts.append("BULLISH_TECHNICAL_WEAK_SECTOR")

    if candidate.score >= 60 and realtime is not None and realtime.confirmation_status == "CONTRADICTORY":
        conflicts.append("HIGH_MTF_SCORE_NEGATIVE_LIVE_CONFIRMATION")

    delivery_evidence = next((e for e in candidate.institutional_footprint.evidence if e.label == "Delivery behaviour proxy"), None)
    volume_expanding = candidate.volume.volume_ratio is not None and candidate.volume.volume_ratio >= 1.3
    if volume_expanding and delivery_evidence is not None and isinstance(delivery_evidence.value, (int, float)) and delivery_evidence.value < 50:
        conflicts.append("VOLUME_EXPANSION_WEAK_DELIVERY")

    if candidate.technical.breakout_status == "BREAKOUT" and candidate.fno.positioning_proxy == "SHORT_BUILDUP_PROXY":
        conflicts.append("PRICE_BREAKOUT_SHORT_BUILDUP")

    if candidate.score >= 60 and candidate.sector_context.market_regime == "RISK_OFF":
        conflicts.append("STRONG_STOCK_RISK_OFF_MARKET_REGIME")

    if bullish_technical and macro.sector_specific_notes and "adverse" in macro.sector_specific_notes[0].interpretation.lower():
        conflicts.append("POSITIVE_STOCK_STRUCTURE_ADVERSE_SECTOR_MACRO_CONTEXT")

    return conflicts


def _detect_supporting_signals(candidate: CandidateResponse, realtime: RealtimeConfirmationResponse | None) -> list[str]:
    supporting: list[str] = []
    tech_frac = _existing_component_fraction(candidate, "technical_structure")
    bullish_technical = tech_frac is not None and tech_frac >= 0.6

    if bullish_technical and candidate.sector_context.sector_strength_label == "STRONG":
        supporting.append("TECHNICAL_AND_SECTOR_ALIGNED")

    if candidate.score >= 60 and realtime is not None and realtime.confirmation_status in ("SUPPORTIVE", "STRONGLY_SUPPORTIVE"):
        supporting.append("LIVE_CONFIRMATION_SUPPORTS_MTF_SETUP")

    if candidate.technical.breakout_status == "BREAKOUT" and candidate.fno.positioning_proxy in ("LONG_BUILDUP_PROXY", "SHORT_COVERING_PROXY"):
        supporting.append("FNO_POSITIONING_ALIGNED_WITH_BREAKOUT")

    return supporting


def _derive_research_status(score: float | None, conflicts: list[str]) -> str:
    # Contradictions are never hidden to make the score look cleaner
    # (explicit requirement) -- ANY detected conflict forces CONFLICTING,
    # regardless of how high the numeric score otherwise is.
    if conflicts:
        return ResearchStatus.CONFLICTING.value
    if score is None:
        return ResearchStatus.INSUFFICIENT_DATA.value
    if score >= 75:
        return ResearchStatus.HIGH_CONFIRMATION.value
    if score >= 60:
        return ResearchStatus.SUPPORTIVE.value
    if score >= 40:
        return ResearchStatus.NEUTRAL.value
    return ResearchStatus.WEAK.value


def build_research_confirmation(
    candidate: CandidateResponse,
    realtime: RealtimeConfirmationResponse | None,
    macro: GlobalMacroContext,
    vix_context: IndiaVixContext,
    now: dt.datetime | None = None,
) -> ResearchConfirmation:
    now = now or dt.datetime.now(dt.UTC)
    corporate_events = CorporateEventContext()

    components = [
        _build_technical_and_rs_component(candidate),
        _build_institutional_footprint_component(candidate),
        _build_fno_component(candidate),
        _build_live_confirmation_component(realtime),
        _build_regime_and_sentiment_component(candidate, macro),
        _build_sector_context_component(candidate),
        _build_catalyst_news_component(candidate),
        _build_corporate_events_component(),
        _build_data_quality_component(candidate),
    ]

    available = [c for c in components if c.available and c.points_awarded is not None]
    if available:
        total_weight = sum(c.weight for c in available)
        research_score = round(sum(c.points_awarded for c in available) / total_weight * 100, 2) if total_weight else None
    else:
        research_score = None

    conflicts = _detect_conflicts(candidate, realtime, macro)
    supporting = _detect_supporting_signals(candidate, realtime)
    status = _derive_research_status(research_score, conflicts)

    sector_participation, sector_participation_evidence = classify_sector_participation_from_deltas(
        candidate.relative_strength.vs_sector_pct_20d, candidate.technical.trend_structure,
    )

    risk_signals: list[str] = []
    if vix_context.regime in ("ELEVATED", "HIGH"):
        risk_signals.append(f"INDIA_VIX_{vix_context.regime}")
    if candidate.sector_context.market_regime == "RISK_OFF":
        risk_signals.append("MARKET_REGIME_RISK_OFF")
    risk_signals.append("CORPORATE_EVENT_VISIBILITY_UNAVAILABLE")

    missing_data = list(candidate.data_quality.missing_data)
    if vix_context.regime == "INSUFFICIENT_DATA":
        missing_data.append("india_vix")
    if macro.risk_sentiment == "INSUFFICIENT_DATA":
        missing_data.append("global_macro")
    missing_data.append("corporate_events")

    research_data_coverage = {
        "india_vix": vix_context.regime != "INSUFFICIENT_DATA",
        "global_macro": macro.risk_sentiment != "INSUFFICIENT_DATA",
        "news": bool(candidate.news.items),
        "corporate_events": False,
        "live_confirmation": realtime is not None and realtime.confirmation_status != "INSUFFICIENT_DATA",
    }

    source_provenance = {
        "mtf_score": "This project's production scoring_engine.py (unchanged)",
        "live_confirmation": "This project's realtime_confirmation_service.py (unchanged)",
        "india_vix": vix_context.source or "Unavailable this run",
        "global_macro": macro.source,
        "corporate_events": "N/A -- not available (see CorporateEventContext)",
    }

    return ResearchConfirmation(
        symbol=candidate.symbol,
        timestamp=now,
        mtf_score=candidate.score,
        research_confirmation_score=research_score,
        research_status=status,
        component_scores=components,
        component_weights_used=dict(RESEARCH_WEIGHTS),
        technical_context=candidate.technical,
        relative_strength=candidate.relative_strength,
        sector_context=candidate.sector_context,
        sector_participation=sector_participation,
        sector_participation_evidence=sector_participation_evidence,
        volume_accumulation=candidate.volume,
        institutional_proxy_context=candidate.institutional_footprint.model_dump(mode="json"),
        futures_context=candidate.fno,
        live_confirmation=realtime,
        india_vix_context=vix_context,
        global_macro_context=macro,
        news_context=candidate.news,
        corporate_event_context=corporate_events,
        supporting_signals=supporting,
        conflicting_signals=conflicts,
        risk_signals=risk_signals,
        missing_data=missing_data,
        core_data_quality=candidate.data_quality,
        research_data_coverage=research_data_coverage,
        source_provenance=source_provenance,
    )
