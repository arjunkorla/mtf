"""Response models for the Momentum Scanner automation layer.

EXPERIMENTAL and separate from the production MTF score -- see
app/engines/momentum_ranking_engine.py's module docstring. Never imported by
scoring_engine.py, scanner_service.py, or CandidateResponse.
"""

import datetime as dt

from pydantic import BaseModel, Field

from app.core.constants import MOMENTUM_LABEL
from app.schemas.common import EvidenceItem, InstitutionalFootprint
from app.schemas.mtf_leverage import MtfLeverageResult
from app.schemas.stock import RelativeStrengthData


class BulkBlockDealEvidence(BaseModel):
    """Always DATA_NOT_AVAILABLE today: no bulk/block-deal data source
    exists in this codebase, and none is being built for this feature (see
    AGENTS.md -- never fabricate institutional/bulk-deal evidence). This is
    a schema placeholder only, exactly like CorporateEventContext's existing
    NOT_AVAILABLE precedent (app/schemas/research.py)."""

    status: str = "DATA_NOT_AVAILABLE"
    bulk_deals: list[dict] = Field(default_factory=list)
    block_deals: list[dict] = Field(default_factory=list)
    fii_dii_activity: str = "DATA_NOT_AVAILABLE"
    promoter_insider_activity: str = "DATA_NOT_AVAILABLE"
    institutional_ownership_change: str = "DATA_NOT_AVAILABLE"


class MomentumRankComponent(BaseModel):
    """One weighted component of evidence_score -- same available/re-normalize
    contract as scoring_engine.py's ScoreComponent (see MOMENTUM_SCAN_WEIGHTS
    in app/core/constants.py)."""

    name: str
    weight: float
    points_awarded: float | None = None
    available: bool
    reason_unavailable: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)


class MomentumCandidate(BaseModel):
    rank: int
    symbol: str
    company_name: str
    price: float

    return_5d_pct: float | None = None
    return_10d_pct: float | None = None
    return_20d_pct: float | None = None
    volume_vs_20d_avg: float | None = None
    delivery_pct: float | None = None

    institutional_footprint: InstitutionalFootprint
    bulk_block_evidence: BulkBlockDealEvidence = Field(default_factory=BulkBlockDealEvidence)
    breakout_status: str | None = None
    rsi_14: float | None = None
    relative_strength: RelativeStrengthData

    mtf_leverage: MtfLeverageResult

    risk_flags: list[str] = Field(default_factory=list)

    evidence_score: float | None = None
    rank_components: list[MomentumRankComponent] = Field(default_factory=list)
    reason_qualified: str

    last_updated: dt.datetime
    disclaimer: str = MOMENTUM_LABEL


class MomentumScanResponse(BaseModel):
    run_id: int
    generated_at: dt.datetime
    scan_slot: str
    top_10: list[MomentumCandidate]
    top_5_verified_3x_mtf: list[MomentumCandidate]
    disclaimer: str = MOMENTUM_LABEL
