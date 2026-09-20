from app.data.normalization import normalize_history
from app.engines.technical_engine import compute_technical_metrics
from app.integrations.fyers.mock_responses import mock_history_response


def test_insufficient_data_returns_none_fields():
    candles = normalize_history(mock_history_response(bars=10))
    result = compute_technical_metrics(candles)
    assert result.trend_structure == "INSUFFICIENT_DATA"
    assert result.ema_20 is None
    assert result.rsi_14 is None


def test_sufficient_data_computes_indicators():
    candles = normalize_history(mock_history_response(bars=260))
    result = compute_technical_metrics(candles)

    assert result.ema_20 is not None
    assert result.ema_50 is not None
    assert result.ema_200 is not None
    assert result.rsi_14 is not None
    assert 0 <= result.rsi_14 <= 100
    assert result.atr_14 is not None and result.atr_14 > 0
    assert result.recent_high_20d >= result.recent_low_20d
    assert result.trend_structure != "INSUFFICIENT_DATA"
    assert result.breakout_status in ("BREAKOUT", "APPROACHING_BREAKOUT", "NO_BREAKOUT")


def test_candles_sorted_chronologically():
    candles = normalize_history(mock_history_response(bars=50))
    dates = [c.trade_date for c in candles]
    assert dates == sorted(dates)
