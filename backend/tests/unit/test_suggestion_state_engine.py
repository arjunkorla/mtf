"""Phase A: deterministic suggestion state machine. Pure-function tests, no
database, no network, no clock."""

import datetime as dt

import pytest

from app.core.suggestion_constants import (
    Direction,
    ObservationSource,
    ObservedPriceBasis,
    SuggestionEventType,
    SuggestionOutcome,
    SuggestionStatus,
)
from app.engines.suggestion_state_engine import (
    Bar,
    SuggestionState,
    Tick,
    apply_bar,
    apply_tick,
    cancel,
    exit_before_close,
    on_session_close,
)

S = SuggestionStatus
O = SuggestionOutcome
E = SuggestionEventType
UTC = dt.UTC
GEN = dt.datetime(2026, 9, 28, 4, 30, tzinfo=UTC)  # 10:00 IST


def t(minutes: int) -> dt.datetime:
    return GEN + dt.timedelta(minutes=minutes)


def long_state(**kw) -> SuggestionState:
    base = dict(direction=Direction.LONG.value, entry_low=100.0, entry_high=102.0, target_1=110.0, target_2=120.0,
                stop_loss=95.0, generated_at=GEN)
    base.update(kw)
    return SuggestionState(**base)


def short_state(**kw) -> SuggestionState:
    base = dict(direction=Direction.SHORT.value, entry_low=98.0, entry_high=100.0, target_1=90.0, target_2=80.0,
                stop_loss=105.0, generated_at=GEN)
    base.update(kw)
    return SuggestionState(**base)


def bar(start_min: int, o: float, h: float, lo: float, c: float, minutes: int = 1, source=ObservationSource.CANDLE_1M.value) -> Bar:
    return Bar(start=t(start_min), end=t(start_min + minutes), open=o, high=h, low=lo, close=c, source=source)


def run(state, *observations):
    events = []
    for obs in observations:
        state, evs = (apply_tick if isinstance(obs, Tick) else apply_bar)(state, obs)
        events.extend(evs)
    return state, events


# ---- fresh touch -------------------------------------------------------------------


def test_new_suggestion_waits_for_entry_even_if_price_already_in_zone():
    s = long_state()
    assert s.status == S.WAITING_ENTRY and s.outcome == O.PENDING

    # A print exactly at generation time is not post-creation evidence.
    s, events = apply_tick(s, Tick(at=GEN, price=101.0))
    assert s.status == S.WAITING_ENTRY and events == []

    # A candle that started before generation mixes pre-creation prices.
    s, events = apply_bar(s, Bar(start=GEN - dt.timedelta(minutes=1), end=GEN + dt.timedelta(minutes=4),
                                 open=101, high=101.5, low=100.5, close=101))
    assert s.status == S.WAITING_ENTRY and events == []

    s, events = apply_tick(s, Tick(at=t(1), price=101.2))
    assert s.status == S.ACTIVE
    assert s.entry_triggered_at == t(1) and s.entry_triggered_price == 101.2
    assert [e.event_type for e in events] == [E.ENTRY_TRIGGERED]


def test_price_outside_zone_does_not_trigger_entry():
    s, events = run(long_state(), Tick(t(1), 104.0), Tick(t(2), 99.0))  # jumped across without a print in zone
    assert s.status == S.WAITING_ENTRY and events == []


# ---- LONG / SHORT transitions -----------------------------------------------------------


def test_long_entry_target1_target2():
    s, events = run(long_state(), Tick(t(1), 101.0), Tick(t(2), 110.5), Tick(t(3), 121.0))
    assert [e.event_type for e in events] == [E.ENTRY_TRIGGERED, E.TARGET_1_HIT, E.TARGET_2_HIT]
    assert s.status == S.TARGET_2_HIT and s.outcome == O.SUCCESS_TARGET_2
    assert s.target_1_hit_price == 110.5 and s.target_2_hit_price == 121.0
    assert s.closed_at == t(3) and s.close_price == 121.0
    assert s.realized_or_marked_return_pct == pytest.approx(19.802, abs=1e-3)
    assert s.return_is_realized is True
    assert s.max_favorable_excursion == pytest.approx(19.802, abs=1e-3)


def test_long_stop_is_failed_stop():
    s, events = run(long_state(), Tick(t(1), 101.0), Tick(t(2), 97.0), Tick(t(3), 94.5))
    assert s.status == S.STOP_HIT and s.outcome == O.FAILED_STOP
    assert s.stop_hit_price == 94.5 and events[-1].threshold_price == 95.0
    assert s.realized_or_marked_return_pct < 0
    assert s.max_adverse_excursion == pytest.approx((94.5 - 101) / 101 * 100, abs=1e-3)


def test_short_entry_target1_target2():
    s, events = run(short_state(), Tick(t(1), 99.0), Tick(t(2), 89.5), Tick(t(3), 79.0))
    assert [e.event_type for e in events] == [E.ENTRY_TRIGGERED, E.TARGET_1_HIT, E.TARGET_2_HIT]
    assert s.outcome == O.SUCCESS_TARGET_2
    assert s.realized_or_marked_return_pct == pytest.approx((99 - 79) / 99 * 100, abs=1e-3)


def test_short_stop_is_failed_stop_with_negative_return():
    s, _ = run(short_state(), Tick(t(1), 99.0), Tick(t(2), 105.5))
    assert s.status == S.STOP_HIT and s.outcome == O.FAILED_STOP
    assert s.realized_or_marked_return_pct == pytest.approx((99 - 105.5) / 99 * 100, abs=1e-3)


def test_short_invalidated_before_entry():
    s, events = run(short_state(), Tick(t(1), 106.0))
    assert s.status == S.INVALIDATED and s.outcome == O.INVALIDATED_BEFORE_ENTRY
    assert s.entry_triggered_at is None and s.realized_or_marked_return_pct is None


# ---- target 1 then stop -----------------------------------------------------------------


def test_target1_then_stop_is_partial_success_and_stop_is_not_moved():
    s, events = run(long_state(), Tick(t(1), 101.0), Tick(t(2), 111.0), Tick(t(3), 100.5), Tick(t(4), 94.0))
    assert s.status == S.STOP_HIT and s.outcome == O.PARTIAL_SUCCESS
    assert s.stop_loss == 95.0  # original stop -- never moved to breakeven
    # Breakeven-after-T1 study data, recorded without changing state:
    assert s.breakeven_revisited_after_target_1_at == t(3)
    assert s.post_target_1_adverse_price == 94.0
    types = [e.event_type for e in events]
    assert types == [E.ENTRY_TRIGGERED, E.TARGET_1_HIT, E.BREAKEVEN_REVISITED_AFTER_TARGET_1, E.STOP_HIT]
    breakeven = events[2]
    assert breakeven.from_status == breakeven.to_status == S.TARGET_1_HIT
    assert breakeven.detail["study_only"] is True


# ---- before entry -------------------------------------------------------------------------


def test_stop_before_entry_is_invalidated_not_failed():
    s, events = run(long_state(), Tick(t(1), 96.0), Tick(t(2), 94.9))
    assert s.status == S.INVALIDATED and s.outcome == O.INVALIDATED_BEFORE_ENTRY
    assert events[0].threshold_price == 95.0 and events[0].observed_market_price == 94.9


def test_explicit_invalidation_level_is_used_before_entry():
    s, _ = run(long_state(invalidation_price=97.0), Tick(t(1), 96.5))
    assert s.outcome == O.INVALIDATED_BEFORE_ENTRY


def test_bar_gapping_below_invalidation_before_entry():
    s, events = apply_bar(long_state(), bar(5, o=93.0, h=94.0, lo=92.0, c=93.5))
    assert s.status == S.INVALIDATED
    ev = events[0]
    assert ev.observed_price_basis == ObservedPriceBasis.GAP_OPEN
    assert ev.threshold_price == 95.0 and ev.observed_market_price == 93.0


# ---- time-based -----------------------------------------------------------------------------


def test_entry_window_expiry_is_no_entry_not_a_loss():
    deadline = dt.date(2026, 10, 6)
    s = long_state(entry_deadline_session_date=deadline)
    s, events = on_session_close(s, dt.date(2026, 10, 5), 104.0, t(60 * 24 * 7))
    assert s.status == S.WAITING_ENTRY and events == []
    s, events = on_session_close(s, deadline, 104.0, t(60 * 24 * 8))
    assert s.status == S.NO_ENTRY and s.outcome == O.NO_ENTRY
    assert s.realized_or_marked_return_pct is None  # never counted as a trade
    assert events[0].event_type == E.NO_ENTRY


def test_max_holding_expiry():
    s, _ = run(long_state(), Tick(t(1), 101.0), Tick(t(2), 104.0))
    s.holding_deadline_session_date = dt.date(2026, 10, 27)
    s, events = on_session_close(s, dt.date(2026, 10, 26), 105.0, t(100))
    assert s.status == S.ACTIVE and events == []
    s, events = on_session_close(s, dt.date(2026, 10, 27), 106.0, t(200))
    assert s.status == S.EXPIRED and s.outcome == O.EXPIRED
    assert s.close_price == 106.0 and s.realized_or_marked_return_pct == pytest.approx(4.9505, abs=1e-3)


def test_max_holding_expiry_after_target1_is_success_target1():
    s, _ = run(long_state(), Tick(t(1), 101.0), Tick(t(2), 112.0))
    s.holding_deadline_session_date = dt.date(2026, 10, 27)
    s, _ = on_session_close(s, dt.date(2026, 10, 27), 108.0, t(200))
    assert s.status == S.EXPIRED and s.outcome == O.SUCCESS_TARGET_1


def test_expiry_requires_a_real_close_price():
    s, _ = run(long_state(), Tick(t(1), 101.0))
    s.holding_deadline_session_date = dt.date(2026, 10, 27)
    with pytest.raises(ValueError):
        on_session_close(s, dt.date(2026, 10, 27), None, t(200))


def test_exit_before_close():
    s, _ = run(long_state(), Tick(t(1), 101.0))
    s, events = exit_before_close(s, t(300), 103.0, ObservationSource.QUOTE.value)
    assert s.status == S.EXIT_BEFORE_CLOSE and s.outcome == O.EXIT_BEFORE_CLOSE
    s2, _ = exit_before_close(long_state(), t(300), 103.0, ObservationSource.QUOTE.value)
    assert s2.status == S.NO_ENTRY


def test_cancel_and_terminal_is_final():
    s, _ = run(long_state(), Tick(t(1), 101.0))
    s, events = cancel(s, t(5), "data feed lost")
    assert s.status == S.CANCELLED and s.outcome == O.CANCELLED and s.failure_reason == "data feed lost"
    s2, events2 = run(s, Tick(t(6), 130.0), bar(7, 90, 91, 80, 85))
    assert s2.status == S.CANCELLED and events2 == []


# ---- same-bar ambiguity ------------------------------------------------------------------------


def test_same_bar_target_and_stop_is_conservative_stop_first():
    s, _ = run(long_state(), Tick(t(1), 101.0))
    s, events = apply_bar(s, bar(10, o=103, h=112, lo=94, c=100))
    assert s.status == S.STOP_HIT and s.outcome == O.FAILED_STOP
    assert s.ambiguous_bar is True and events[-1].ambiguous_bar is True
    assert events[-1].detail["target_1_touched_in_bar"] is True
    assert s.max_favorable_price == 101.0  # the high may postdate the stop: not credited


def test_same_bar_after_target1_stop_and_target2_is_partial_success_ambiguous():
    s, _ = run(long_state(), Tick(t(1), 101.0), Tick(t(2), 111.0))
    s, events = apply_bar(s, bar(10, o=112, h=121, lo=94, c=100))
    assert s.status == S.STOP_HIT and s.outcome == O.PARTIAL_SUCCESS and s.ambiguous_bar is True


def test_ordered_ticks_are_never_ambiguous():
    s, events = run(long_state(), Tick(t(1), 101.0), Tick(t(2), 111.0), Tick(t(3), 94.0))
    assert s.outcome == O.PARTIAL_SUCCESS and s.ambiguous_bar is False
    assert all(not e.ambiguous_bar for e in events)


def test_target1_and_target2_in_one_bar_is_not_ambiguous():
    s, _ = run(long_state(), Tick(t(1), 101.0))
    s, events = apply_bar(s, bar(10, o=104, h=125, lo=103, c=124))
    assert [e.event_type for e in events] == [E.TARGET_1_HIT, E.TARGET_2_HIT]
    assert s.outcome == O.SUCCESS_TARGET_2 and s.ambiguous_bar is False


def test_entry_bar_from_stop_side_touching_stop_is_ambiguous_failed():
    s, events = apply_bar(long_state(), bar(10, o=97, h=101, lo=94, c=100))
    assert s.status == S.STOP_HIT and s.outcome == O.FAILED_STOP and s.ambiguous_bar is True


def test_entry_bar_from_target_side_does_not_credit_target():
    s, events = apply_bar(long_state(), bar(10, o=111, h=112, lo=101, c=103))
    assert s.status == S.ACTIVE and s.entry_triggered_price == 102.0  # travelled down through the zone top
    assert s.ambiguous_bar is True and s.target_1_hit_at is None
    assert events[0].observed_price_basis == ObservedPriceBasis.WITHIN_BAR_RANGE


def test_entry_bar_opening_in_zone_is_fully_post_entry():
    s, events = apply_bar(long_state(), bar(10, o=101, h=111, lo=100.5, c=110))
    assert [e.event_type for e in events] == [E.ENTRY_TRIGGERED, E.TARGET_1_HIT]
    assert s.entry_triggered_price == 101 and events[0].observed_price_basis == ObservedPriceBasis.OPEN_IN_ZONE
    assert s.ambiguous_bar is False


# ---- gaps -------------------------------------------------------------------------------------------


def test_gap_across_targets_records_threshold_and_observed_separately():
    s, _ = run(long_state(), Tick(t(1), 101.0))
    s, events = apply_bar(s, bar(60 * 24, o=125, h=126, lo=124, c=125.5, source=ObservationSource.CANDLE_D.value))
    assert [e.event_type for e in events] == [E.TARGET_1_HIT, E.TARGET_2_HIT]
    for ev, threshold in zip(events, (110.0, 120.0)):
        assert ev.threshold_price == threshold
        assert ev.observed_market_price == 125
        assert ev.observed_price_basis == ObservedPriceBasis.GAP_OPEN
    assert s.close_price == 125 and s.outcome == O.SUCCESS_TARGET_2


def test_gap_across_stop_uses_observed_open_not_the_stop():
    s, _ = run(long_state(), Tick(t(1), 101.0))
    s, events = apply_bar(s, bar(60 * 24, o=90, h=96, lo=89, c=95))
    ev = events[-1]
    assert ev.event_type == E.STOP_HIT
    assert ev.threshold_price == 95.0 and ev.observed_market_price == 90
    assert ev.observed_price_basis == ObservedPriceBasis.GAP_OPEN
    assert s.realized_or_marked_return_pct == pytest.approx((90 - 101) / 101 * 100, abs=1e-3)


def test_short_gap_across_stop():
    s, _ = run(short_state(), Tick(t(1), 99.0))
    s, events = apply_bar(s, bar(60 * 24, o=108, h=109, lo=104, c=107))
    assert events[-1].event_type == E.STOP_HIT and events[-1].observed_market_price == 108
    assert s.outcome == O.FAILED_STOP


def test_gap_across_target1_then_stop_later_in_same_bar_is_ordered():
    s, _ = run(long_state(), Tick(t(1), 101.0))
    s, events = apply_bar(s, bar(60 * 24, o=112, h=113, lo=94, c=96))
    # The open is the first price: T1 is known to precede the stop.
    assert [e.event_type for e in events][:1] == [E.TARGET_1_HIT]
    assert s.outcome == O.PARTIAL_SUCCESS and s.ambiguous_bar is False


def test_bars_containing_pre_entry_prices_are_skipped():
    s, _ = run(long_state(), Tick(t(5), 101.0))
    s, events = apply_bar(s, bar(4, o=101, h=101, lo=80, c=100, minutes=5))  # starts before entry
    assert s.status == S.ACTIVE and events == []
