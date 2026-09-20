import datetime as dt

from app.data.internal_models import Candle
from app.engines.backtest_engine import compute_historical_signal, evaluate_forward_outcome
from app.integrations.fyers.mock_responses import mock_history_response
from app.data.normalization import normalize_history


def _candle(day_offset: int, low: float, high: float, close: float | None = None) -> Candle:
    base = dt.date(2026, 1, 1) + dt.timedelta(days=day_offset)
    return Candle(trade_date=base, open=low, high=high, low=low, close=close if close is not None else high, volume=100_000)


def test_evaluate_forward_outcome_target_1_hit():
    future = [
        _candle(1, low=99, high=101, close=100),
        _candle(2, low=100, high=112, close=111),  # touches resistance_1=110
        _candle(3, low=110, high=115, close=114),
    ]
    outcome = evaluate_forward_outcome(future, entry_price=100, invalidation_price=90, resistance_1=110, resistance_2=130, holding_period_days=20)
    assert outcome.label == "TARGET_1_HIT"
    assert outcome.trading_days_to_outcome == 2
    assert outcome.forward_return_pct == 10.0


def test_evaluate_forward_outcome_invalidated():
    future = [
        _candle(1, low=95, high=101, close=98),
        _candle(2, low=85, high=100, close=90),  # breaches invalidation=90
    ]
    outcome = evaluate_forward_outcome(future, entry_price=100, invalidation_price=90, resistance_1=110, resistance_2=130, holding_period_days=20)
    assert outcome.label == "INVALIDATED"
    assert outcome.trading_days_to_outcome == 2
    assert outcome.forward_return_pct == -10.0


def test_invalidation_checked_before_resistance_same_day():
    """Conservative (risk-first) tie-break when a single daily bar's range
    spans both the invalidation price and a resistance level."""
    future = [_candle(1, low=85, high=115, close=100)]
    outcome = evaluate_forward_outcome(future, entry_price=100, invalidation_price=90, resistance_1=110, resistance_2=None, holding_period_days=20)
    assert outcome.label == "INVALIDATED"


def test_evaluate_forward_outcome_time_exit():
    future = [_candle(i, low=99, high=105, close=102) for i in range(1, 6)]
    outcome = evaluate_forward_outcome(future, entry_price=100, invalidation_price=90, resistance_1=110, resistance_2=130, holding_period_days=5)
    assert outcome.label == "TIME_EXIT"
    assert outcome.trading_days_to_outcome == 5
    assert outcome.forward_return_pct == 2.0


def test_evaluate_forward_outcome_insufficient_data_when_history_runs_out():
    future = [_candle(i, low=99, high=105, close=102) for i in range(1, 3)]  # only 2 bars
    outcome = evaluate_forward_outcome(future, entry_price=100, invalidation_price=90, resistance_1=110, resistance_2=130, holding_period_days=20)
    assert outcome.label == "INSUFFICIENT_FORWARD_DATA"
    assert outcome.forward_return_pct is None


def test_evaluate_forward_outcome_no_future_candles():
    outcome = evaluate_forward_outcome([], entry_price=100, invalidation_price=90, resistance_1=110, resistance_2=130, holding_period_days=20)
    assert outcome.label == "INSUFFICIENT_FORWARD_DATA"


def test_compute_historical_signal_excludes_fundamentals_news_fno():
    candles = normalize_history(mock_history_response(bars=260))
    signal = compute_historical_signal(candles, candles, None, "IT")

    names = {c["name"]: c for c in signal.score_components}
    assert names["fundamentals"]["available"] is False
    assert names["catalyst_news"]["available"] is False
    assert names["fno_positioning"]["available"] is False
    # Technical/volume ARE point-in-time-safe and should be available given 260 candles.
    assert names["technical_structure"]["available"] is True
    assert names["volume_accumulation"]["available"] is True


def test_compute_historical_signal_insufficient_history_yields_no_setup():
    candles = normalize_history(mock_history_response(bars=10))
    signal = compute_historical_signal(candles, candles, None, None)
    assert signal.setup_type == "NONE"
