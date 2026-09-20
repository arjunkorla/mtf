"""MTF setup detection (section 17). Identifies a single primary setup type
from technical + volume evidence, with explicit supporting/conflicting
evidence and an invalidation condition. Never predicts guaranteed movement.
"""

from app.core.constants import SetupType
from app.engines.technical_engine import TechnicalResult
from app.schemas.common import EvidenceItem, SetupDetection
from app.schemas.stock import RelativeStrengthData, VolumeData


def detect_setup(
    technical: TechnicalResult,
    volume: VolumeData,
    relative_strength: RelativeStrengthData,
) -> SetupDetection:
    supporting: list[EvidenceItem] = []
    conflicting: list[EvidenceItem] = []

    if technical.trend_structure == "INSUFFICIENT_DATA":
        return SetupDetection(
            setup_type=SetupType.NONE.value,
            setup_strength=None,
            supporting_evidence=[],
            conflicting_evidence=[],
            invalidation_condition=None,
        )

    setup_type = SetupType.NONE
    strength = "LOW"

    if technical.breakout_status == "BREAKOUT" and volume.volume_ratio and volume.volume_ratio >= 1.5:
        setup_type = SetupType.ACCUMULATION_BREAKOUT if (volume.accumulation_score or 0) >= 60 else SetupType.BREAKOUT
        strength = "HIGH"
        supporting.append(EvidenceItem(
            label="Breakout with volume",
            detail=f"Price at/near 20D high with {volume.volume_ratio:.2f}x average volume",
            is_positive=True,
        ))
    elif technical.pullback_status == "PULLBACK_TO_SUPPORT" and technical.trend_structure in ("STRONG_UPTREND", "UPTREND"):
        setup_type = SetupType.PULLBACK
        strength = "MEDIUM"
        supporting.append(EvidenceItem(
            label="Pullback in uptrend",
            detail="Price has pulled back toward EMA20/EMA50 support within an established uptrend",
            is_positive=True,
        ))
    elif technical.breakout_status == "APPROACHING_BREAKOUT":
        setup_type = SetupType.BREAKOUT_RETEST
        strength = "MEDIUM"
        supporting.append(EvidenceItem(
            label="Approaching resistance",
            detail="Price is within 3% of the 20D high, a potential breakout/retest zone",
            is_positive=True,
        ))
    elif relative_strength.label == "OUTPERFORM" and technical.trend_structure in ("STRONG_UPTREND", "UPTREND"):
        setup_type = SetupType.RELATIVE_STRENGTH_CONTINUATION
        strength = "MEDIUM"
        supporting.append(EvidenceItem(
            label="Relative strength continuation",
            detail="Stock outperforming NIFTY within an active uptrend",
            is_positive=True,
        ))
    elif technical.trend_structure in ("STRONG_UPTREND", "UPTREND"):
        setup_type = SetupType.TREND_CONTINUATION
        strength = "LOW"
        supporting.append(EvidenceItem(
            label="Established uptrend",
            detail="EMA stack in bullish order (price > EMA20 > EMA50 > EMA200 or similar)",
            is_positive=True,
        ))

    if technical.rsi_14 is not None and technical.rsi_14 >= 75:
        conflicting.append(EvidenceItem(
            label="Overbought RSI",
            detail=f"RSI14 at {technical.rsi_14:.1f}, elevated extension risk",
            value=technical.rsi_14,
            is_positive=False,
        ))
    if volume.high_volume_down_days_20d and volume.high_volume_up_days_20d is not None and volume.high_volume_down_days_20d > volume.high_volume_up_days_20d:
        conflicting.append(EvidenceItem(
            label="More distribution than accumulation days",
            detail="High-volume down days outnumber high-volume up days over the last 20 sessions",
            is_positive=False,
        ))
    if relative_strength.label == "UNDERPERFORM":
        conflicting.append(EvidenceItem(
            label="Relative weakness",
            detail="Stock underperforming NIFTY over the recent window",
            is_positive=False,
        ))

    invalidation = None
    if technical.support_level is not None:
        invalidation = f"Daily close below {technical.support_level:.2f} (support/EMA structure)"

    return SetupDetection(
        setup_type=setup_type.value,
        setup_strength=strength if setup_type != SetupType.NONE else None,
        supporting_evidence=supporting,
        conflicting_evidence=conflicting,
        invalidation_condition=invalidation,
    )
