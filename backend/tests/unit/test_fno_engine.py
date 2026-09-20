from app.core.constants import FnoPositioningProxy
from app.engines.fno_engine import classify_positioning, compute_fno_metrics
from app.data.internal_models import FuturesContract


def test_long_buildup_proxy():
    assert classify_positioning(price_change_pct=2.0, oi_change_pct=5.0) == FnoPositioningProxy.LONG_BUILDUP


def test_short_buildup_proxy():
    assert classify_positioning(price_change_pct=-2.0, oi_change_pct=5.0) == FnoPositioningProxy.SHORT_BUILDUP


def test_short_covering_proxy():
    assert classify_positioning(price_change_pct=2.0, oi_change_pct=-5.0) == FnoPositioningProxy.SHORT_COVERING


def test_long_unwinding_proxy():
    assert classify_positioning(price_change_pct=-2.0, oi_change_pct=-5.0) == FnoPositioningProxy.LONG_UNWINDING


def test_neutral_when_flat():
    assert classify_positioning(price_change_pct=0.05, oi_change_pct=0.1) == FnoPositioningProxy.NEUTRAL


def test_not_available_when_not_fno():
    result = compute_fno_metrics(is_fno_stock=False, futures=None)
    assert result.is_available is False
    assert result.positioning_proxy == FnoPositioningProxy.NOT_AVAILABLE.value


def test_available_with_futures_contract():
    futures = FuturesContract(symbol="NSE:TEST24DECFUT", ltp=100, open_interest=1_000_000, oi_change_pct=3.5, volume=500_000)
    result = compute_fno_metrics(is_fno_stock=True, futures=futures)
    assert result.is_available is True
    assert result.futures_oi_change_pct == 3.5


def test_uses_real_futures_price_change_when_present():
    """Phase 1 F&O investigation: price_change_pct used to be hardcoded to
    0.0 (a stub, since no data source populated it) -- now that
    FuturesContract carries the real value (from /data/depth's 'chp'), it
    must actually be used, not silently ignored in favor of the old stub."""
    futures = FuturesContract(
        symbol="NSE:TEST26SEPFUT", ltp=100, open_interest=1_000_000,
        oi_change_pct=5.0, volume=500_000, price_change_pct=2.0,
    )
    result = compute_fno_metrics(is_fno_stock=True, futures=futures)
    assert result.futures_price_change_pct == 2.0
    # price up (2.0%) + OI up (5.0%) -> LONG_BUILDUP_PROXY, not NEUTRAL
    assert result.positioning_proxy == FnoPositioningProxy.LONG_BUILDUP.value


def test_price_change_defaults_to_zero_when_genuinely_absent():
    futures = FuturesContract(
        symbol="NSE:TEST26SEPFUT", ltp=100, open_interest=1_000_000,
        oi_change_pct=5.0, volume=500_000, price_change_pct=None,
    )
    result = compute_fno_metrics(is_fno_stock=True, futures=futures)
    assert result.futures_price_change_pct == 0.0


def test_put_call_ratio_computed_when_oi_totals_supplied():
    futures = FuturesContract(symbol="NSE:TEST26SEPFUT", ltp=100, open_interest=1_000_000, oi_change_pct=1.0, volume=500_000)
    result = compute_fno_metrics(is_fno_stock=True, futures=futures, call_oi_total=4_500_000, put_oi_total=5_100_000)
    assert result.put_call_oi_ratio == round(5_100_000 / 4_500_000, 3)
