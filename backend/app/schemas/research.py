"""Response models for the research confirmation layer (Phase 5).

EXPERIMENTAL and separate from the production MTF score -- see
app/engines/research_confirmation_engine.py's module docstring for the
component-weighting rationale and the double-counting analysis behind it.
Never imported by scoring_engine.py, scanner_service.py, or CandidateResponse.
"""

import datetime as dt

from pydantic import BaseModel, Field

from app.schemas.common import DataQuality, EvidenceItem
from app.schemas.confirmation import RealtimeConfirmationResponse
from app.schemas.scanner import CandidateResponse
from app.schemas.stock import FnoData, NewsData, RelativeStrengthData, SectorData, TechnicalData, VolumeData

RESEARCH_LABEL = "EXPERIMENTAL -- NOT PRODUCTION VALIDATED"


class ResearchComponentScore(BaseModel):
    """One weighted component of research_confirmation_score -- same
    available/re-normalize contract as scoring_engine.py's ScoreComponent
    (see RESEARCH_WEIGHTS in app/core/constants.py)."""

    name: str
    weight: float
    points_awarded: float | None = None
    available: bool
    reason_unavailable: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)


class MacroContextItem(BaseModel):
    """One macro instrument's contribution to a candidate's global-context
    evidence. Every field the frontend/API needs to avoid presenting an
    unofficial, possibly-stale, possibly-closed-market number as a live,
    authoritative signal (Phase 5 Step 9 provenance requirement)."""

    label: str  # e.g. "USD/INR"
    symbol: str  # provider's own symbol, e.g. "INR=X"
    value: float
    change_pct: float | None
    as_of: dt.datetime
    session_state: str  # MacroSessionState
    affected_dimension: str  # e.g. "IT/Pharma export revenue (context only)"
    interpretation: str
    confidence: str  # "LOW" | "MEDIUM" -- never "HIGH": this is context, not a causal signal
    source: str


class IndiaVixContext(BaseModel):
    value: float | None
    regime: str  # VixRegime
    as_of: dt.datetime | None
    source: str | None
    note: str


class GlobalMacroContext(BaseModel):
    risk_sentiment: str  # GlobalRiskSentiment -- derived only from broad global equity indices
    broad_instruments: list[MacroContextItem] = Field(default_factory=list)
    sector_specific_notes: list[MacroContextItem] = Field(default_factory=list)
    source: str


class CorporateEventContext(BaseModel):
    status: str = "NOT_AVAILABLE"
    reason: str = (
        "No verified, stable, free/no-auth NSE corporate-events source was found "
        "(live-tested 2026-09-21: corporate-announcements/corporate-actions/financial-results/"
        "board-meetings all return HTTP 403 on nseindia.com's API to non-browser clients; only "
        "paid third-party providers or fragile scrapers exist). Not implemented, not fabricated."
    )


class ResearchConfirmation(BaseModel):
    symbol: str
    timestamp: dt.datetime
    label: str = RESEARCH_LABEL

    mtf_score: float  # pass-through from CandidateResponse.score -- never recomputed here
    research_confirmation_score: float | None
    research_status: str  # ResearchStatus

    component_scores: list[ResearchComponentScore]
    component_weights_used: dict[str, float]

    technical_context: TechnicalData
    relative_strength: RelativeStrengthData
    sector_context: SectorData
    volume_accumulation: VolumeData
    institutional_proxy_context: dict  # InstitutionalFootprint.model_dump() pass-through
    futures_context: FnoData
    live_confirmation: RealtimeConfirmationResponse | None
    india_vix_context: IndiaVixContext
    global_macro_context: GlobalMacroContext
    news_context: NewsData
    corporate_event_context: CorporateEventContext

    supporting_signals: list[str] = Field(default_factory=list)
    conflicting_signals: list[str] = Field(default_factory=list)
    risk_signals: list[str] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)

    core_data_quality: DataQuality  # pass-through from CandidateResponse.data_quality
    research_data_coverage: dict[str, bool]  # which OPTIONAL research sources were available this run
    source_provenance: dict[str, str]


class ResearchComparisonRow(BaseModel):
    """One row of the MTF-rank-vs-research-rank comparison (Phase 5 Step
    12) -- a reporting aid only, never a re-ranking of scanner output."""

    symbol: str
    mtf_score: float
    mtf_rank: int
    research_confirmation_score: float | None
    research_rank: int | None
    research_status: str
    delta_note: str
