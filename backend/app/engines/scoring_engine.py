"""MTF scoring engine (section 15).

Transparent, component-based score out of 100. Unavailable components are
NEVER awarded positive points -- the total is re-normalized against the sum
of weights of the components that WERE available, and every component is
returned separately so the frontend can explain exactly how the score was
built (spec requirement).
"""

from app.core.constants import SCORE_WEIGHTS, SignalQuality
from app.engines.technical_engine import TechnicalResult
from app.schemas.common import EvidenceItem, ScoreComponent
from app.schemas.stock import (
    FnoData,
    FundamentalData,
    NewsData,
    RelativeStrengthData,
    SectorData,
    VolumeData,
)


def _technical_points(technical: TechnicalResult, weight: float) -> ScoreComponent:
    if technical.trend_structure == "INSUFFICIENT_DATA":
        return ScoreComponent(name="technical_structure", weight=weight, available=False,
                               reason_unavailable="Fewer than 20 daily candles available")

    trend_scores = {
        "STRONG_UPTREND": 1.0, "UPTREND": 0.75, "RANGE_BOUND": 0.4,
        "DOWNTREND": 0.15, "STRONG_DOWNTREND": 0.0,
    }
    breakout_bonus = {"BREAKOUT": 1.0, "APPROACHING_BREAKOUT": 0.6, "NO_BREAKOUT": 0.3, "INSUFFICIENT_DATA": 0.0}
    frac = 0.7 * trend_scores.get(technical.trend_structure, 0.3) + 0.3 * breakout_bonus.get(technical.breakout_status, 0.3)
    points = round(frac * weight, 2)
    return ScoreComponent(
        name="technical_structure", weight=weight, points_awarded=points, available=True,
        evidence=[EvidenceItem(
            label="Trend structure", detail=f"{technical.trend_structure}, breakout status {technical.breakout_status}",
            is_positive=frac >= 0.5,
        )],
    )


def _volume_points(volume: VolumeData, weight: float) -> ScoreComponent:
    if volume.accumulation_score is None:
        return ScoreComponent(name="volume_accumulation", weight=weight, available=False,
                               reason_unavailable="Fewer than 20 daily candles available")
    frac = volume.accumulation_score / 100.0
    points = round(frac * weight, 2)
    return ScoreComponent(
        name="volume_accumulation", weight=weight, points_awarded=points, available=True,
        evidence=list(volume.evidence),
    )


def _relative_strength_points(rs: RelativeStrengthData, weight: float) -> ScoreComponent:
    if rs.label == "INSUFFICIENT_DATA":
        return ScoreComponent(name="relative_strength", weight=weight, available=False,
                               reason_unavailable="No index/sector history available for comparison")
    frac = {"OUTPERFORM": 1.0, "NEUTRAL": 0.5, "UNDERPERFORM": 0.0}.get(rs.label, 0.5)
    points = round(frac * weight, 2)
    return ScoreComponent(
        name="relative_strength", weight=weight, points_awarded=points, available=True,
        evidence=[EvidenceItem(label="Relative strength vs NIFTY (20D)", detail=rs.label,
                                value=rs.vs_nifty_pct_20d, is_positive=frac >= 0.5)],
    )


def _fno_points(fno: FnoData, weight: float) -> ScoreComponent:
    if not fno.is_available:
        return ScoreComponent(name="fno_positioning", weight=weight, available=False,
                               reason_unavailable="Not an F&O stock or F&O data unavailable")
    frac = {
        "LONG_BUILDUP_PROXY": 1.0, "SHORT_COVERING_PROXY": 0.75, "NEUTRAL": 0.5,
        "LONG_UNWINDING_PROXY": 0.25, "SHORT_BUILDUP_PROXY": 0.0,
    }.get(fno.positioning_proxy, 0.5)
    points = round(frac * weight, 2)
    return ScoreComponent(
        name="fno_positioning", weight=weight, points_awarded=points, available=True,
        evidence=list(fno.evidence),
    )


def _fundamental_points(f: FundamentalData, weight: float) -> ScoreComponent:
    if not f.is_available:
        return ScoreComponent(name="fundamentals", weight=weight, available=False,
                               reason_unavailable="No validated fundamentals on file for this stock")
    checks = []
    if f.revenue_growth_yoy_pct is not None:
        checks.append(f.revenue_growth_yoy_pct > 5)
    if f.profit_growth_yoy_pct is not None:
        checks.append(f.profit_growth_yoy_pct > 5)
    if f.roe_pct is not None:
        checks.append(f.roe_pct > 12)
    if f.debt_to_equity is not None:
        checks.append(f.debt_to_equity < 1.0)
    if not checks:
        return ScoreComponent(name="fundamentals", weight=weight, available=False,
                               reason_unavailable="Fundamentals record present but all fields empty")
    frac = sum(checks) / len(checks)
    points = round(frac * weight, 2)
    return ScoreComponent(name="fundamentals", weight=weight, points_awarded=points, available=True)


def _news_points(news: NewsData, weight: float) -> ScoreComponent:
    if news.overall_sentiment == "UNKNOWN":
        return ScoreComponent(name="catalyst_news", weight=weight, available=False,
                               reason_unavailable="No recent news/catalyst data available")
    frac = {"POSITIVE": 1.0, "NEUTRAL": 0.5, "NEGATIVE": 0.0}.get(news.overall_sentiment, 0.5)
    points = round(frac * weight, 2)
    return ScoreComponent(name="catalyst_news", weight=weight, points_awarded=points, available=True)


def _market_sector_points(sector: SectorData, weight: float) -> ScoreComponent:
    if sector.market_regime in (None, "INSUFFICIENT_DATA") and sector.sector_strength_label is None:
        return ScoreComponent(name="market_sector", weight=weight, available=False,
                               reason_unavailable="Market regime / sector strength could not be determined")
    regime_frac = {"RISK_ON": 1.0, "NEUTRAL": 0.5, "RISK_OFF": 0.0}.get(sector.market_regime, 0.5)
    sector_frac = {"STRONG": 1.0, "NEUTRAL": 0.5, "WEAK": 0.0}.get(sector.sector_strength_label, 0.5)
    frac = (regime_frac + sector_frac) / 2
    points = round(frac * weight, 2)
    return ScoreComponent(name="market_sector", weight=weight, points_awarded=points, available=True)


def _data_quality_points(data_quality_score_0_100: float, weight: float) -> ScoreComponent:
    frac = data_quality_score_0_100 / 100.0
    points = round(frac * weight, 2)
    return ScoreComponent(name="data_quality", weight=weight, points_awarded=points, available=True)


def compute_score(
    technical: TechnicalResult,
    volume: VolumeData,
    relative_strength: RelativeStrengthData,
    fno: FnoData,
    fundamentals: FundamentalData,
    news: NewsData,
    sector: SectorData,
    data_quality_score_0_100: float,
) -> tuple[float, list[ScoreComponent], str]:
    components = [
        _technical_points(technical, SCORE_WEIGHTS["technical_structure"]),
        _volume_points(volume, SCORE_WEIGHTS["volume_accumulation"]),
        _relative_strength_points(relative_strength, SCORE_WEIGHTS["relative_strength"]),
        _fno_points(fno, SCORE_WEIGHTS["fno_positioning"]),
        _fundamental_points(fundamentals, SCORE_WEIGHTS["fundamentals"]),
        _news_points(news, SCORE_WEIGHTS["catalyst_news"]),
        _market_sector_points(sector, SCORE_WEIGHTS["market_sector"]),
        _data_quality_points(data_quality_score_0_100, SCORE_WEIGHTS["data_quality"]),
    ]

    available = [c for c in components if c.available]
    available_weight = sum(c.weight for c in available)
    awarded = sum(c.points_awarded or 0.0 for c in available)

    if available_weight == 0:
        total_score = 0.0
    else:
        # Re-normalize to a 0-100 scale based on weights actually available.
        total_score = round(awarded / available_weight * 100, 2)

    if total_score >= 70 and len(available) >= 5:
        quality = SignalQuality.HIGH.value
    elif total_score >= 50 and len(available) >= 4:
        quality = SignalQuality.MEDIUM.value
    else:
        quality = SignalQuality.LOW.value

    return total_score, components, quality
