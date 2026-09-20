from app.core.constants import InstitutionalFootprintLevel
from app.data.bhavcopy_parser import DeliveryMetrics
from app.engines.institutional_footprint_engine import compute_institutional_footprint
from app.schemas.stock import FnoData, RelativeStrengthData, VolumeData


def _volume(volume_ratio=None, up=None, down=None, accumulation=None, breakout_volume=None):
    return VolumeData(
        volume_ratio=volume_ratio,
        relative_volume=volume_ratio,
        high_volume_up_days_20d=up,
        high_volume_down_days_20d=down,
        breakout_volume=breakout_volume,
        accumulation_score=accumulation,
        evidence=[],
    )


def test_insufficient_data_when_too_few_proxies():
    volume = _volume()  # nothing available
    rs = RelativeStrengthData(label="INSUFFICIENT_DATA")
    fno = FnoData(is_available=False, positioning_proxy="NOT_AVAILABLE")

    result = compute_institutional_footprint(volume, rs, fno)
    assert result.institutional_footprint_level == InstitutionalFootprintLevel.INSUFFICIENT_DATA.value
    assert result.institutional_footprint_score is None


def test_strong_footprint_with_bullish_proxies():
    volume = _volume(volume_ratio=2.0, up=6, down=1, accumulation=85, breakout_volume=1_000_000)
    rs = RelativeStrengthData(label="OUTPERFORM", vs_nifty_pct_20d=5.0)
    fno = FnoData(is_available=True, positioning_proxy="LONG_BUILDUP_PROXY", futures_oi_change_pct=8.0)

    result = compute_institutional_footprint(volume, rs, fno)
    assert result.institutional_footprint_score is not None
    assert result.institutional_footprint_level in (
        InstitutionalFootprintLevel.STRONG.value,
        InstitutionalFootprintLevel.MODERATE.value,
    )
    assert len(result.evidence) >= 3


def test_never_claims_institutions_are_buying():
    volume = _volume(volume_ratio=2.0, up=6, down=1, accumulation=85, breakout_volume=1_000_000)
    rs = RelativeStrengthData(label="OUTPERFORM", vs_nifty_pct_20d=5.0)
    fno = FnoData(is_available=True, positioning_proxy="LONG_BUILDUP_PROXY", futures_oi_change_pct=8.0)
    delivery = DeliveryMetrics(symbol="TEST", total_traded_qty=1000, delivery_qty=770, delivery_percentage=77.0)

    result = compute_institutional_footprint(volume, rs, fno, delivery)
    for item in result.evidence:
        assert "institutions are buying" not in item.detail.lower()
        assert "institutions are buying" not in item.label.lower()


def test_delivery_proxy_absent_when_not_supplied():
    """Backtest mode never supplies delivery data (no point-in-time
    history) -- the proxy must simply not appear, not be faked."""
    volume = _volume(volume_ratio=2.0, up=6, down=1, accumulation=85, breakout_volume=1_000_000)
    rs = RelativeStrengthData(label="OUTPERFORM", vs_nifty_pct_20d=5.0)
    fno = FnoData(is_available=True, positioning_proxy="LONG_BUILDUP_PROXY", futures_oi_change_pct=8.0)

    result = compute_institutional_footprint(volume, rs, fno)
    assert not any("delivery" in e.label.lower() for e in result.evidence)


def test_delivery_proxy_included_and_scored_when_supplied():
    volume = _volume(volume_ratio=2.0, up=6, down=1, accumulation=85, breakout_volume=1_000_000)
    rs = RelativeStrengthData(label="OUTPERFORM", vs_nifty_pct_20d=5.0)
    fno = FnoData(is_available=True, positioning_proxy="LONG_BUILDUP_PROXY", futures_oi_change_pct=8.0)
    high_delivery = DeliveryMetrics(symbol="TEST", total_traded_qty=1000, delivery_qty=900, delivery_percentage=90.0)

    result = compute_institutional_footprint(volume, rs, fno, high_delivery)
    delivery_evidence = [e for e in result.evidence if "delivery" in e.label.lower()]
    assert len(delivery_evidence) == 1
    assert delivery_evidence[0].is_positive is True
    assert delivery_evidence[0].value == 90.0


def test_low_delivery_percentage_is_negative_signal():
    low_delivery = DeliveryMetrics(symbol="TEST", total_traded_qty=1000, delivery_qty=100, delivery_percentage=10.0)
    volume = _volume(volume_ratio=1.0, up=1, down=1, accumulation=50)
    rs = RelativeStrengthData(label="NEUTRAL", vs_nifty_pct_20d=0.0)
    fno = FnoData(is_available=False, positioning_proxy="NOT_AVAILABLE")

    result = compute_institutional_footprint(volume, rs, fno, low_delivery)
    delivery_evidence = next(e for e in result.evidence if "delivery" in e.label.lower())
    assert delivery_evidence.is_positive is False
