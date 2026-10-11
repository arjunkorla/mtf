"""Momentum Scanner ranking engine (automation layer).

EXPERIMENTAL, separate from the production MTF score (scoring_engine.py,
never imported here) and from the Research Confirmation layer. Reads an
already-built CandidateResponse plus data this feature adds (MtfLeverageResult,
5D/10D/20D returns) and produces a NEW weighted composite (MOMENTUM_SCAN_WEIGHTS
in app/core/constants.py) specific to this automation's ranking spec.

Same re-normalization contract as scoring_engine.py/research_confirmation_engine.py:
each component contributes points_awarded = frac * weight when available;
unavailable components are excluded from the score entirely (never scored as
zero, never rewarded for being absent). bulk_block_deal_evidence is always
unavailable -- no bulk/block-deal data source exists in this codebase (see
AGENTS.md) -- and liquidity is unavailable too, since CandidateResponse
exposes no raw turnover/volume figure independent of the volume ratio; both
are honest gaps, not approximated.

If fewer than MIN_AVAILABLE_COMPONENTS are available, evidence_score is None
(insufficient evidence to rank), matching institutional_footprint_engine.py's
MIN_AVAILABLE_PROXIES gating.
"""

from app.core.constants import MOMENTUM_SCAN_WEIGHTS, MtfLeverageStatus
from app.schemas.common import EvidenceItem
from app.schemas.momentum_scan import MomentumRankComponent
from app.schemas.mtf_leverage import MtfLeverageResult
from app.schemas.scanner import CandidateResponse

MIN_AVAILABLE_COMPONENTS = 3


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _delivery_pct(candidate: CandidateResponse) -> float | None:
    item = next(
        (e for e in candidate.institutional_footprint.evidence if e.label == "Delivery behaviour proxy"), None
    )
    return item.value if item is not None and isinstance(item.value, (int, float)) else None


def _institutional_footprint_component(candidate: CandidateResponse) -> MomentumRankComponent:
    weight = MOMENTUM_SCAN_WEIGHTS["institutional_footprint"]
    fp = candidate.institutional_footprint
    if fp.institutional_footprint_score is None:
        return MomentumRankComponent(
            name="institutional_footprint", weight=weight, available=False,
            reason_unavailable="Fewer than the minimum number of institutional-footprint proxies were available",
        )
    frac = fp.institutional_footprint_score / 100.0
    return MomentumRankComponent(
        name="institutional_footprint", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=fp.evidence,
    )


def _bulk_block_deal_component() -> MomentumRankComponent:
    weight = MOMENTUM_SCAN_WEIGHTS["bulk_block_deal_evidence"]
    return MomentumRankComponent(
        name="bulk_block_deal_evidence", weight=weight, available=False,
        reason_unavailable="No bulk/block-deal data source exists in this codebase (DATA_NOT_AVAILABLE)",
    )


def _volume_and_delivery_component(candidate: CandidateResponse) -> MomentumRankComponent:
    weight = MOMENTUM_SCAN_WEIGHTS["volume_and_delivery"]
    volume_ratio = candidate.volume.volume_ratio
    delivery_pct = _delivery_pct(candidate)

    fracs = []
    evidence: list[EvidenceItem] = []
    if volume_ratio is not None:
        fracs.append(_clamp(0.5 + (volume_ratio - 1) * 0.4))
        evidence.append(
            EvidenceItem(
                label="Volume vs 20D average", detail=f"{volume_ratio:.2f}x the 20-day average volume",
                value=volume_ratio, is_positive=volume_ratio >= 2.0,
            )
        )
    if delivery_pct is not None:
        fracs.append(_clamp(0.5 + (delivery_pct - 50) * 0.015))
        evidence.append(
            EvidenceItem(
                label="Delivery percentage", detail=f"{delivery_pct:.1f}% delivery (NSE bhavcopy)",
                value=delivery_pct, is_positive=delivery_pct >= 55,
            )
        )

    if not fracs:
        return MomentumRankComponent(
            name="volume_and_delivery", weight=weight, available=False,
            reason_unavailable="Neither volume ratio nor delivery percentage was available",
        )

    frac = sum(fracs) / len(fracs)
    return MomentumRankComponent(
        name="volume_and_delivery", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=evidence,
    )


def _technical_momentum_component(
    rsi_14: float | None, return_20d_pct: float | None,
) -> MomentumRankComponent:
    weight = MOMENTUM_SCAN_WEIGHTS["technical_momentum"]
    fracs = []
    evidence: list[EvidenceItem] = []
    if return_20d_pct is not None:
        fracs.append(_clamp(0.5 + return_20d_pct / 40))
        evidence.append(
            EvidenceItem(
                label="20-day return", detail=f"{return_20d_pct:+.2f}% over the last 20 sessions",
                value=return_20d_pct, is_positive=return_20d_pct > 0,
            )
        )
    if rsi_14 is not None:
        # Peaks around RSI 60 (sustained momentum, not yet overbought) --
        # rewards early/continuation momentum, penalizes both a stalled
        # setup (low RSI) and an overextended one (RSI well above 70).
        fracs.append(_clamp(1 - abs(rsi_14 - 60) / 40))
        evidence.append(
            EvidenceItem(
                label="RSI(14)", detail=f"RSI(14) at {rsi_14:.1f}",
                value=rsi_14, is_positive=50 <= rsi_14 <= 70,
            )
        )

    if not fracs:
        return MomentumRankComponent(
            name="technical_momentum", weight=weight, available=False,
            reason_unavailable="Neither 20-day return nor RSI(14) was available",
        )

    frac = sum(fracs) / len(fracs)
    return MomentumRankComponent(
        name="technical_momentum", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=evidence,
    )


_BREAKOUT_FRACTIONS = {
    "BREAKOUT": 0.9,
    "APPROACHING_BREAKOUT": 0.65,
    "NO_BREAKOUT": 0.35,
}


def _breakout_structure_component(candidate: CandidateResponse) -> MomentumRankComponent:
    weight = MOMENTUM_SCAN_WEIGHTS["breakout_structure"]
    status = candidate.technical.breakout_status
    frac = _BREAKOUT_FRACTIONS.get(status)
    if frac is None:
        return MomentumRankComponent(
            name="breakout_structure", weight=weight, available=False,
            reason_unavailable="Breakout status unavailable or insufficient technical history",
        )
    return MomentumRankComponent(
        name="breakout_structure", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=[EvidenceItem(label="Breakout status", detail=status, value=status, is_positive=status != "NO_BREAKOUT")],
    )


_RS_FRACTIONS = {"OUTPERFORM": 0.75, "NEUTRAL": 0.5, "UNDERPERFORM": 0.25}


def _relative_strength_component(candidate: CandidateResponse) -> MomentumRankComponent:
    weight = MOMENTUM_SCAN_WEIGHTS["relative_strength"]
    rs = candidate.relative_strength
    frac = _RS_FRACTIONS.get(rs.label)
    if frac is None:
        return MomentumRankComponent(
            name="relative_strength", weight=weight, available=False,
            reason_unavailable="Relative strength vs NIFTY was insufficient data",
        )
    return MomentumRankComponent(
        name="relative_strength", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=[EvidenceItem(
            label="Relative strength vs NIFTY", detail=f"Labeled {rs.label}", value=rs.vs_nifty_pct_20d,
            is_positive=rs.label == "OUTPERFORM",
        )],
    )


def _liquidity_component() -> MomentumRankComponent:
    weight = MOMENTUM_SCAN_WEIGHTS["liquidity"]
    return MomentumRankComponent(
        name="liquidity", weight=weight, available=False,
        reason_unavailable="CandidateResponse exposes no raw turnover/volume figure independent of the volume ratio",
    )


def _mtf_characteristics_component(mtf_leverage: MtfLeverageResult) -> MomentumRankComponent:
    weight = MOMENTUM_SCAN_WEIGHTS["mtf_characteristics"]
    if mtf_leverage.mtf_status != MtfLeverageStatus.VERIFIED.value or mtf_leverage.effective_leverage is None:
        return MomentumRankComponent(
            name="mtf_characteristics", weight=weight, available=False,
            reason_unavailable=mtf_leverage.reason_unverified or "MTF leverage not verified",
        )
    frac = _clamp(mtf_leverage.effective_leverage / 5.0)
    return MomentumRankComponent(
        name="mtf_characteristics", weight=weight, points_awarded=round(frac * weight, 2), available=True,
        evidence=list(mtf_leverage.evidence),
    )


def compute_momentum_rank(
    candidate: CandidateResponse,
    mtf_leverage: MtfLeverageResult,
    return_5d_pct: float | None,
    return_10d_pct: float | None,
    return_20d_pct: float | None,
) -> tuple[float | None, list[MomentumRankComponent]]:
    components = [
        _institutional_footprint_component(candidate),
        _bulk_block_deal_component(),
        _volume_and_delivery_component(candidate),
        _technical_momentum_component(candidate.technical.rsi_14, return_20d_pct),
        _breakout_structure_component(candidate),
        _relative_strength_component(candidate),
        _liquidity_component(),
        _mtf_characteristics_component(mtf_leverage),
    ]

    available = [c for c in components if c.available and c.points_awarded is not None]
    if len(available) < MIN_AVAILABLE_COMPONENTS:
        return None, components

    total_weight = sum(c.weight for c in available)
    if total_weight <= 0:
        return None, components

    evidence_score = round(sum(c.points_awarded for c in available) / total_weight * 100, 2)
    return evidence_score, components


def build_reason_qualified(components: list[MomentumRankComponent]) -> str:
    """Names the components that materially supported qualification -- never
    a generic "looks bullish" claim, always tied to specific evidence."""
    strong = [c for c in components if c.available and c.points_awarded is not None and c.weight > 0 and (c.points_awarded / c.weight) >= 0.6]
    if not strong:
        return "Qualified on available evidence, though no single component was strongly positive"
    labels = {
        "institutional_footprint": "institutional footprint proxy",
        "volume_and_delivery": "volume/delivery expansion",
        "technical_momentum": "technical momentum",
        "breakout_structure": "breakout structure",
        "relative_strength": "relative strength vs NIFTY",
        "mtf_characteristics": "verified MTF leverage",
    }
    names = [labels.get(c.name, c.name) for c in strong]
    return "Supported by: " + ", ".join(names)
