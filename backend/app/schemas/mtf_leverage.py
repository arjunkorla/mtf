"""MTF leverage verification result (Momentum Scanner automation).

Never a guessed/default leverage: `effective_leverage` is populated only
when `mtf_status == VERIFIED`. Every other status carries `None` -- see
app/engines/mtf_leverage_engine.py for the enforcement.
"""

from pydantic import BaseModel, Field

from app.schemas.common import EvidenceItem


class MtfLeverageResult(BaseModel):
    mtf_status: str  # MtfLeverageStatus
    required_margin_pct: float | None = None
    effective_leverage: float | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    reason_unverified: str | None = None
