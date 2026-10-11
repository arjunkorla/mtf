"""MTF Leverage Verification Engine (Momentum Scanner automation).

Pure function, no I/O -- mirrors institutional_footprint_engine.py's shape.

Effective leverage = 100 / required_margin_pct. This is ONLY computed when
a real, FYERS-confirmed required-margin-percentage is available. If margin
data cannot be confirmed for any reason (endpoint unavailable, account
restriction, API error, symbol not found), the result is always
MTF_STATUS = UNVERIFIED with effective_leverage = None -- never a guessed or
default leverage. See AGENTS.md: "Never assume leverage."
"""

from app.core.constants import MIN_VERIFIED_LEVERAGE, MtfLeverageStatus
from app.schemas.common import EvidenceItem
from app.schemas.mtf_leverage import MtfLeverageResult


def compute_mtf_leverage(
    symbol_is_mtf_eligible: bool,
    required_margin_pct: float | None,
) -> MtfLeverageResult:
    """`required_margin_pct` is the real FYERS-reported required margin
    percentage for the symbol under MTF, or None if it could not be
    confirmed this run (whatever the reason -- see margin.py)."""
    if not symbol_is_mtf_eligible:
        return MtfLeverageResult(
            mtf_status=MtfLeverageStatus.NOT_MTF_ELIGIBLE.value,
            reason_unverified="Symbol is not flagged MTF-eligible in the current universe",
        )

    if required_margin_pct is None:
        return MtfLeverageResult(
            mtf_status=MtfLeverageStatus.UNVERIFIED.value,
            reason_unverified="FYERS margin data unavailable for this symbol/session",
        )

    if not (0 < required_margin_pct <= 100):
        return MtfLeverageResult(
            mtf_status=MtfLeverageStatus.UNVERIFIED.value,
            reason_unverified=f"FYERS returned an implausible margin percentage ({required_margin_pct}), treated as unverifiable",
        )

    effective_leverage = round(100 / required_margin_pct, 2)
    return MtfLeverageResult(
        mtf_status=MtfLeverageStatus.VERIFIED.value,
        required_margin_pct=required_margin_pct,
        effective_leverage=effective_leverage,
        evidence=[
            EvidenceItem(
                label="FYERS MTF margin verification",
                detail=f"FYERS reports {required_margin_pct:.2f}% required margin under MTF, giving {effective_leverage:.2f}x effective leverage",
                value=effective_leverage,
                is_positive=effective_leverage >= MIN_VERIFIED_LEVERAGE,
            )
        ],
    )
