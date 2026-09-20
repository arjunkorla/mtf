from app.engines.scoring_engine import compute_score
from app.engines.technical_engine import TechnicalResult
from app.schemas.stock import FnoData, FundamentalData, NewsData, RelativeStrengthData, SectorData, VolumeData


def _insufficient_technical():
    return TechnicalResult(
        ema_20=None, ema_50=None, ema_200=None, rsi_14=None, atr_14=None, adx_14=None, vwap=None,
        recent_high_20d=None, recent_low_20d=None, support_level=None, resistance_level=None,
        trend_structure="INSUFFICIENT_DATA", breakout_status="INSUFFICIENT_DATA", pullback_status="INSUFFICIENT_DATA",
    )


def _strong_technical():
    return TechnicalResult(
        ema_20=110, ema_50=105, ema_200=95, rsi_14=60, atr_14=2.5, adx_14=30, vwap=108,
        recent_high_20d=112, recent_low_20d=98, support_level=104, resistance_level=112,
        trend_structure="STRONG_UPTREND", breakout_status="BREAKOUT", pullback_status="NO_PULLBACK",
    )


def test_unavailable_components_award_no_points():
    technical = _insufficient_technical()
    volume = VolumeData(accumulation_score=None, evidence=[])
    rs = RelativeStrengthData(label="INSUFFICIENT_DATA")
    fno = FnoData(is_available=False, positioning_proxy="NOT_AVAILABLE")
    fundamentals = FundamentalData(is_available=False)
    news = NewsData(items=[], overall_sentiment="UNKNOWN")
    sector = SectorData(relative_strength=rs)

    total, components, quality = compute_score(technical, volume, rs, fno, fundamentals, news, sector, 40.0)

    for c in components:
        if not c.available:
            assert c.points_awarded is None
    # Only data_quality is available -> normalized to 0-100 based on that alone.
    available = [c for c in components if c.available]
    assert len(available) == 1
    assert available[0].name == "data_quality"
    assert quality == "LOW"


def test_full_data_produces_high_score_for_bullish_stock():
    technical = _strong_technical()
    volume = VolumeData(
        volume_ratio=1.8, relative_volume=1.8, high_volume_up_days_20d=5, high_volume_down_days_20d=1,
        breakout_volume=900_000, accumulation_score=80, evidence=[],
    )
    rs = RelativeStrengthData(label="OUTPERFORM", vs_nifty_pct_20d=4.0)
    fno = FnoData(is_available=True, positioning_proxy="LONG_BUILDUP_PROXY", futures_oi_change_pct=6.0)
    fundamentals = FundamentalData(is_available=True, revenue_growth_yoy_pct=12, profit_growth_yoy_pct=15, roe_pct=18, debt_to_equity=0.4)
    news = NewsData(items=[], overall_sentiment="POSITIVE")
    sector = SectorData(sector_strength_label="STRONG", market_regime="RISK_ON", relative_strength=rs)

    total, components, quality = compute_score(technical, volume, rs, fno, fundamentals, news, sector, 95.0)

    assert total > 70
    assert quality == "HIGH"
    assert all(c.available for c in components)
    # All 8 weighted components (summing to 100) are available, so no
    # re-normalization occurs: total score equals the raw points sum.
    assert round(sum(c.points_awarded for c in components), 2) == total
