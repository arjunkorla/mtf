from app.data.normalization import normalize_history
from app.engines.volume_engine import compute_volume_metrics
from app.integrations.fyers.mock_responses import mock_history_response


def test_insufficient_history_returns_none():
    candles = normalize_history(mock_history_response(bars=5))
    result = compute_volume_metrics(candles)
    assert result.accumulation_score is None
    assert result.evidence == []


def test_volume_metrics_bounds():
    candles = normalize_history(mock_history_response(bars=100))
    result = compute_volume_metrics(candles)

    assert result.accumulation_score is not None
    assert 0 <= result.accumulation_score <= 100
    assert result.volume_ratio is not None and result.volume_ratio > 0
    assert result.high_volume_up_days_20d >= 0
    assert result.high_volume_down_days_20d >= 0
    assert len(result.evidence) >= 2
