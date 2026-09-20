"""Institutional Footprint Proxy Engine (section 9) -- the most important
engine in the system.

Combines only MEASURABLE proxies into a single score + level. Never asserts
"institutions are buying" -- output is always phrased as
"Institutional Footprint Proxy: <LEVEL>" with supporting evidence, matching
the spec's required language.

Each proxy contributes 0-100 when available; the final score is the average
of AVAILABLE proxies only (unavailable proxies are excluded, never scored as
neutral/zero, so missing data cannot silently drag the score down or up).
If fewer than MIN_AVAILABLE_PROXIES are available, the result is
INSUFFICIENT_DATA regardless of the partial score.
"""

from app.core.constants import FnoPositioningProxy, InstitutionalFootprintLevel, RelativeStrengthLabel
from app.data.bhavcopy_parser import DeliveryMetrics
from app.schemas.common import EvidenceItem, InstitutionalFootprint
from app.schemas.stock import FnoData, RelativeStrengthData, VolumeData

MIN_AVAILABLE_PROXIES = 3


def _volume_expansion_proxy(volume: VolumeData) -> tuple[float, EvidenceItem] | None:
    if volume.volume_ratio is None:
        return None
    score = max(0.0, min(100.0, 50 + (volume.volume_ratio - 1) * 40))
    return score, EvidenceItem(
        label="Volume expansion proxy",
        detail=f"Volume running at {volume.volume_ratio:.2f}x the 20-day average",
        value=volume.volume_ratio,
        is_positive=volume.volume_ratio >= 1.3,
    )


def _price_volume_behaviour_proxy(volume: VolumeData) -> tuple[float, EvidenceItem] | None:
    if volume.high_volume_up_days_20d is None or volume.high_volume_down_days_20d is None:
        return None
    net = volume.high_volume_up_days_20d - volume.high_volume_down_days_20d
    score = max(0.0, min(100.0, 50 + net * 10))
    return score, EvidenceItem(
        label="Price-volume behaviour proxy",
        detail=(
            f"{volume.high_volume_up_days_20d} high-volume up days vs "
            f"{volume.high_volume_down_days_20d} high-volume down days (20D)"
        ),
        value=net,
        is_positive=net > 0,
    )


def _accumulation_proxy(volume: VolumeData) -> tuple[float, EvidenceItem] | None:
    if volume.accumulation_score is None:
        return None
    return volume.accumulation_score, EvidenceItem(
        label="Accumulation behaviour proxy",
        detail=f"Composite accumulation score {volume.accumulation_score:.1f}/100",
        value=volume.accumulation_score,
        is_positive=volume.accumulation_score >= 55,
    )


def _relative_strength_proxy(rs: RelativeStrengthData) -> tuple[float, EvidenceItem] | None:
    if rs.label == RelativeStrengthLabel.INSUFFICIENT_DATA.value:
        return None
    mapping = {
        RelativeStrengthLabel.OUTPERFORM.value: 75.0,
        RelativeStrengthLabel.NEUTRAL.value: 50.0,
        RelativeStrengthLabel.UNDERPERFORM.value: 25.0,
    }
    score = mapping.get(rs.label, 50.0)
    return score, EvidenceItem(
        label="Relative strength proxy",
        detail=f"Stock is labeled {rs.label} vs NIFTY over the recent window",
        value=rs.vs_nifty_pct_20d,
        is_positive=rs.label == RelativeStrengthLabel.OUTPERFORM.value,
    )


def _fno_proxy(fno: FnoData) -> tuple[float, EvidenceItem] | None:
    if not fno.is_available or fno.positioning_proxy == FnoPositioningProxy.NOT_AVAILABLE.value:
        return None
    mapping = {
        FnoPositioningProxy.LONG_BUILDUP.value: 80.0,
        FnoPositioningProxy.SHORT_COVERING.value: 65.0,
        FnoPositioningProxy.NEUTRAL.value: 50.0,
        FnoPositioningProxy.LONG_UNWINDING.value: 35.0,
        FnoPositioningProxy.SHORT_BUILDUP.value: 20.0,
    }
    score = mapping.get(fno.positioning_proxy, 50.0)
    return score, EvidenceItem(
        label="F&O positioning proxy",
        detail=f"Futures price/OI pattern classified as {fno.positioning_proxy}",
        value=fno.futures_oi_change_pct,
        is_positive=fno.positioning_proxy in (
            FnoPositioningProxy.LONG_BUILDUP.value,
            FnoPositioningProxy.SHORT_COVERING.value,
        ),
    )


def _large_volume_activity_proxy(volume: VolumeData) -> tuple[float, EvidenceItem] | None:
    if volume.breakout_volume is None:
        return None
    return 70.0, EvidenceItem(
        label="Large-volume activity proxy",
        detail="A session with >=1.5x average volume occurred recently",
        value=volume.breakout_volume,
        is_positive=True,
    )


def _delivery_proxy(delivery: DeliveryMetrics | None) -> tuple[float, EvidenceItem] | None:
    if delivery is None:
        return None
    score = max(0.0, min(100.0, 50 + (delivery.delivery_percentage - 50) * 1.5))
    return score, EvidenceItem(
        label="Delivery behaviour proxy",
        detail=f"{delivery.delivery_percentage:.1f}% of traded quantity resulted in delivery (NSE bhavcopy)",
        value=delivery.delivery_percentage,
        is_positive=delivery.delivery_percentage >= 55,
    )


def compute_institutional_footprint(
    volume: VolumeData,
    relative_strength: RelativeStrengthData,
    fno: FnoData,
    delivery: DeliveryMetrics | None = None,
) -> InstitutionalFootprint:
    """`delivery` is optional and defaults to unavailable: backtest mode
    (app/engines/backtest_engine.py) never passes it, since this system has
    no point-in-time delivery history -- the same look-ahead-bias reasoning
    that already excludes fundamentals/news/F&O there. Sector relative
    strength is folded into `relative_strength` (see market_sector_engine.py)
    rather than scored as a separate proxy here.
    """
    proxies = [
        _volume_expansion_proxy(volume),
        _price_volume_behaviour_proxy(volume),
        _accumulation_proxy(volume),
        _relative_strength_proxy(relative_strength),
        _fno_proxy(fno),
        _large_volume_activity_proxy(volume),
        _delivery_proxy(delivery),
    ]
    available = [p for p in proxies if p is not None]

    if len(available) < MIN_AVAILABLE_PROXIES:
        return InstitutionalFootprint(
            institutional_footprint_score=None,
            institutional_footprint_level=InstitutionalFootprintLevel.INSUFFICIENT_DATA.value,
            evidence=[e for _, e in available],
        )

    scores = [s for s, _ in available]
    evidence = [e for _, e in available]
    avg_score = sum(scores) / len(scores)

    if avg_score >= 70:
        level = InstitutionalFootprintLevel.STRONG
    elif avg_score >= 55:
        level = InstitutionalFootprintLevel.MODERATE
    elif avg_score >= 40:
        level = InstitutionalFootprintLevel.NEUTRAL
    else:
        level = InstitutionalFootprintLevel.WEAK

    return InstitutionalFootprint(
        institutional_footprint_score=round(avg_score, 2),
        institutional_footprint_level=level.value,
        evidence=evidence,
    )
