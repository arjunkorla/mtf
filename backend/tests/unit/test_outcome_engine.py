import datetime as dt

from app.data.internal_models import Candle
from app.engines.outcome_engine import OUTCOME_COMPUTED, OUTCOME_PARTIAL, OUTCOME_PENDING, compute_outcome


def _candle(day_offset: int, close: float, high: float | None = None, low: float | None = None) -> Candle:
    return Candle(
        trade_date=dt.date(2026, 9, 1) + dt.timedelta(days=day_offset),
        open=close, high=high if high is not None else close + 1, low=low if low is not None else close - 1,
        close=close, volume=100_000,
    )


def test_pending_when_no_future_candles():
    result = compute_outcome(observed_price=100.0, invalidation=90.0, entry_zone_low=95.0, entry_zone_high=100.0, future_candles=[])
    assert result.status == OUTCOME_PENDING
    assert result.next_1d_return is None


def test_pending_when_observed_price_missing_never_fabricated():
    candles = [_candle(i, 100.0 + i) for i in range(1, 25)]
    result = compute_outcome(observed_price=None, invalidation=90.0, entry_zone_low=95.0, entry_zone_high=100.0, future_candles=candles)
    assert result.status == OUTCOME_PENDING
    assert result.next_20d_return is None


def test_partial_when_only_some_horizons_have_real_candles():
    candles = [_candle(i, 100.0 + i) for i in range(1, 4)]  # only 3 future candles
    result = compute_outcome(observed_price=100.0, invalidation=90.0, entry_zone_low=95.0, entry_zone_high=100.0, future_candles=candles)
    assert result.status == OUTCOME_PARTIAL
    assert result.next_1d_return is not None
    assert result.next_3d_return is not None
    assert result.next_5d_return is None  # not enough real candles yet -- never fabricated
    assert result.next_10d_return is None
    assert result.next_20d_return is None


def test_computed_when_all_five_horizons_have_real_candles():
    candles = [_candle(i, 100.0 + i) for i in range(1, 25)]  # 24 future candles, well past 20D
    result = compute_outcome(observed_price=100.0, invalidation=90.0, entry_zone_low=95.0, entry_zone_high=100.0, future_candles=candles)
    assert result.status == OUTCOME_COMPUTED
    assert all(
        v is not None
        for v in (result.next_1d_return, result.next_3d_return, result.next_5d_return, result.next_10d_return, result.next_20d_return)
    )
    # close on day 1 (index 0) = 101.0 -> (101-100)/100*100 = 1.0%
    assert result.next_1d_return == 1.0


def test_invalidation_hit_true_when_a_future_low_breaches_it():
    candles = [_candle(1, 100.0, low=95.0), _candle(2, 102.0, low=101.0)]
    result = compute_outcome(observed_price=100.0, invalidation=96.0, entry_zone_low=95.0, entry_zone_high=100.0, future_candles=candles)
    assert result.invalidation_hit is True


def test_invalidation_hit_false_when_never_breached():
    candles = [_candle(1, 105.0, low=103.0), _candle(2, 108.0, low=104.0)]
    result = compute_outcome(observed_price=100.0, invalidation=90.0, entry_zone_low=95.0, entry_zone_high=100.0, future_candles=candles)
    assert result.invalidation_hit is False


def test_invalidation_hit_none_when_invalidation_price_unknown():
    candles = [_candle(1, 105.0)]
    result = compute_outcome(observed_price=100.0, invalidation=None, entry_zone_low=95.0, entry_zone_high=100.0, future_candles=candles)
    assert result.invalidation_hit is None


def test_entry_zone_reached_true_when_price_crosses_the_zone():
    candles = [_candle(1, 110.0, high=112.0, low=108.0), _candle(2, 97.0, high=99.0, low=96.0)]
    result = compute_outcome(observed_price=100.0, invalidation=90.0, entry_zone_low=95.0, entry_zone_high=100.0, future_candles=candles)
    assert result.entry_zone_reached is True


def test_mfe_and_mae_reflect_real_extremes():
    candles = [_candle(1, 105.0, high=110.0, low=98.0), _candle(2, 95.0, high=106.0, low=90.0)]
    result = compute_outcome(observed_price=100.0, invalidation=80.0, entry_zone_low=95.0, entry_zone_high=100.0, future_candles=candles)
    assert result.maximum_favorable_excursion == 10.0  # (110-100)/100
    assert result.maximum_adverse_excursion == -10.0  # (90-100)/100
