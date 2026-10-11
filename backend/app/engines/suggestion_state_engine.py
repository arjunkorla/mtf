"""Deterministic suggestion lifecycle state machine (Phase A).

Pure functions: (state, observation) -> (new_state, events). No database, no
network, no clock reads -- every timestamp comes from the observation, so
the same inputs always produce the same transitions.

Rules (all approved in the Phase A brief):

  Fresh touch   A suggestion starts WAITING_ENTRY. Only observations made
                strictly AFTER generated_at can trigger entry -- being inside
                the zone at generation time is not an entry. A candle that
                started before generated_at mixes pre- and post-generation
                prices, so it is ignored entirely.

  Entry         A trade print inside [entry_low, entry_high], or a candle
                whose range overlaps the zone.

  Before entry  Reaching the invalidation level (invalidation_price, or the
                stop when none is given) -> INVALIDATED /
                INVALIDATED_BEFORE_ENTRY. Never counted as a failed trade.

  In position   stop -> STOP_HIT (FAILED_STOP, or PARTIAL_SUCCESS if target 1
                was already hit). target 1 -> TARGET_1_HIT. target 2 ->
                TARGET_2_HIT (SUCCESS_TARGET_2). The ORIGINAL stop is never
                moved to breakeven; post-target-1 adverse movement and the
                first breakeven revisit are recorded as study data only.

  Gaps          If a candle OPENS beyond a threshold, the open is the first
                observed price: the event stores threshold_price and
                observed_market_price separately (basis GAP_OPEN). A
                threshold inside a candle's range is recorded at the
                threshold with basis WITHIN_BAR_RANGE -- never claimed as an
                exact print.

  Same bar      If one candle touches both the stop and a target and its
                ordering cannot be established, the stop is assumed first
                (conservative) and ambiguous_bar=True. Ordered tick evidence
                is never ambiguous.

  Time          on_session_close(): entry deadline -> NO_ENTRY; holding
                deadline -> EXPIRED (SUCCESS_TARGET_1 if target 1 was hit).
                exit_before_close() is the intraday cutoff.
"""

import copy
import dataclasses
import datetime as dt
from dataclasses import dataclass, field

from app.core.suggestion_constants import (
    OPEN_STATUSES,
    TERMINAL_STATUSES,
    Direction,
    ObservationSource,
    ObservedPriceBasis,
    SuggestionEventType,
    SuggestionOutcome,
    SuggestionStatus,
)

S = SuggestionStatus
E = SuggestionEventType
B = ObservedPriceBasis


@dataclass
class SuggestionState:
    direction: str
    entry_low: float
    entry_high: float
    target_1: float
    stop_loss: float
    generated_at: dt.datetime
    target_2: float | None = None
    invalidation_price: float | None = None
    entry_deadline_session_date: dt.date | None = None
    holding_deadline_session_date: dt.date | None = None

    status: str = S.WAITING_ENTRY.value
    outcome: str = SuggestionOutcome.PENDING.value
    entry_triggered_at: dt.datetime | None = None
    entry_triggered_price: float | None = None
    target_1_hit_at: dt.datetime | None = None
    target_1_hit_price: float | None = None
    target_2_hit_at: dt.datetime | None = None
    target_2_hit_price: float | None = None
    stop_hit_at: dt.datetime | None = None
    stop_hit_price: float | None = None
    closed_at: dt.datetime | None = None
    close_price: float | None = None
    max_favorable_price: float | None = None
    max_adverse_price: float | None = None
    max_favorable_excursion: float | None = None
    max_adverse_excursion: float | None = None
    realized_or_marked_return_pct: float | None = None
    return_is_realized: bool = False
    post_target_1_adverse_price: float | None = None
    breakeven_revisited_after_target_1_at: dt.datetime | None = None
    ambiguous_bar: bool = False
    failure_reason: str | None = None
    last_observed_price: float | None = None
    last_observed_at: dt.datetime | None = None


# Fields the engine may change -- everything else in SuggestionState is an
# input copied from the immutable suggestion row.
MUTABLE_STATE_FIELDS = tuple(
    f.name for f in dataclasses.fields(SuggestionState)
    if f.name not in {
        "direction", "entry_low", "entry_high", "target_1", "target_2", "stop_loss", "invalidation_price",
        "generated_at", "entry_deadline_session_date",
    }
)


@dataclass(frozen=True)
class Tick:
    at: dt.datetime
    price: float
    source: str = ObservationSource.TICK.value


@dataclass(frozen=True)
class Bar:
    start: dt.datetime
    end: dt.datetime
    open: float
    high: float
    low: float
    close: float
    source: str = ObservationSource.CANDLE_1M.value

    def __post_init__(self):
        if not (self.low <= min(self.open, self.close) and self.high >= max(self.open, self.close)):
            raise ValueError(f"Inconsistent OHLC bar: {self}")
        if self.end <= self.start:
            raise ValueError("Bar end must be after start")


@dataclass(frozen=True)
class EngineEvent:
    event_type: str
    from_status: str | None
    to_status: str | None
    observed_at: dt.datetime | None
    threshold_price: float | None = None
    observed_market_price: float | None = None
    observed_price_basis: str | None = None
    data_source: str | None = None
    ambiguous_bar: bool = False
    detail: dict = field(default_factory=dict)


# ---- direction helpers -------------------------------------------------------


def _long(s: SuggestionState) -> bool:
    return s.direction == Direction.LONG.value


def _fav_reached(s: SuggestionState, price: float, level: float) -> bool:
    return price >= level if _long(s) else price <= level


def _adv_reached(s: SuggestionState, price: float, level: float) -> bool:
    return price <= level if _long(s) else price >= level


def _fav_extreme(s: SuggestionState, bar: Bar) -> float:
    return bar.high if _long(s) else bar.low


def _adv_extreme(s: SuggestionState, bar: Bar) -> float:
    return bar.low if _long(s) else bar.high


def _more_favorable(s: SuggestionState, a: float, b: float) -> bool:
    return a > b if _long(s) else a < b


def _return_pct(s: SuggestionState, entry: float, price: float) -> float:
    raw = (price - entry) / entry * 100 if _long(s) else (entry - price) / entry * 100
    return round(raw, 4)


def _in_zone(s: SuggestionState, price: float) -> bool:
    return s.entry_low <= price <= s.entry_high


def _zone_side(s: SuggestionState, price: float) -> str:
    """INSIDE, FAVORABLE (target side of the zone) or ADVERSE (stop side)."""
    if _in_zone(s, price):
        return "INSIDE"
    above = price > s.entry_high
    return "FAVORABLE" if above == _long(s) else "ADVERSE"


def _pre_entry_invalidation(s: SuggestionState) -> float:
    return s.invalidation_price if s.invalidation_price is not None else s.stop_loss


# ---- transitions ---------------------------------------------------------------


def _terminal_outcome(prev_status: str, new_status: str) -> str:
    O = SuggestionOutcome
    if new_status == S.TARGET_2_HIT:
        return O.SUCCESS_TARGET_2.value
    if new_status == S.STOP_HIT:
        return O.PARTIAL_SUCCESS.value if prev_status == S.TARGET_1_HIT else O.FAILED_STOP.value
    if new_status == S.INVALIDATED:
        return O.INVALIDATED_BEFORE_ENTRY.value
    if new_status == S.NO_ENTRY:
        return O.NO_ENTRY.value
    if new_status == S.EXPIRED:
        return O.SUCCESS_TARGET_1.value if prev_status == S.TARGET_1_HIT else O.EXPIRED.value
    if new_status == S.EXIT_BEFORE_CLOSE:
        return O.SUCCESS_TARGET_1.value if prev_status == S.TARGET_1_HIT else O.EXIT_BEFORE_CLOSE.value
    if new_status == S.CANCELLED:
        return O.CANCELLED.value
    raise ValueError(f"{new_status} is not terminal")


def _transition(
    s: SuggestionState, events: list[EngineEvent], new_status: S, event_type: E, at: dt.datetime | None,
    threshold: float | None, observed: float | None, basis: B | None, source: str | None,
    ambiguous: bool = False, detail: dict | None = None,
) -> None:
    prev = s.status
    s.status = new_status.value
    if ambiguous:
        s.ambiguous_bar = True
    if new_status in TERMINAL_STATUSES:
        s.outcome = _terminal_outcome(prev, new_status.value)
        s.closed_at = at
        s.close_price = observed
    events.append(EngineEvent(
        event_type=event_type.value, from_status=prev, to_status=new_status.value, observed_at=at,
        threshold_price=threshold, observed_market_price=observed,
        observed_price_basis=basis.value if basis else None, data_source=source, ambiguous_bar=ambiguous,
        detail=detail or {},
    ))


def _enter(s: SuggestionState, events: list[EngineEvent], at: dt.datetime, price: float, basis: B, source: str) -> None:
    s.entry_triggered_at = at
    s.entry_triggered_price = price
    s.max_favorable_price = price
    s.max_adverse_price = price
    _transition(
        s, events, S.ACTIVE, E.ENTRY_TRIGGERED, at, threshold=min(max(price, s.entry_low), s.entry_high),
        observed=price, basis=basis, source=source,
        detail={"entry_low": s.entry_low, "entry_high": s.entry_high},
    )


def _hit_stop(s, events, at, observed, basis, source, ambiguous=False, detail=None) -> None:
    s.stop_hit_at, s.stop_hit_price = at, observed
    _transition(s, events, S.STOP_HIT, E.STOP_HIT, at, s.stop_loss, observed, basis, source, ambiguous, detail)


def _hit_target_1(s, events, at, observed, basis, source) -> None:
    s.target_1_hit_at, s.target_1_hit_price = at, observed
    s.post_target_1_adverse_price = observed
    _transition(s, events, S.TARGET_1_HIT, E.TARGET_1_HIT, at, s.target_1, observed, basis, source)


def _hit_target_2(s, events, at, observed, basis, source) -> None:
    s.target_2_hit_at, s.target_2_hit_price = at, observed
    _transition(s, events, S.TARGET_2_HIT, E.TARGET_2_HIT, at, s.target_2, observed, basis, source)


def _update_excursions(s: SuggestionState, favorable: float | None, adverse: float | None) -> None:
    if favorable is not None and (s.max_favorable_price is None or _more_favorable(s, favorable, s.max_favorable_price)):
        s.max_favorable_price = favorable
    if adverse is not None and (s.max_adverse_price is None or _more_favorable(s, s.max_adverse_price, adverse)):
        s.max_adverse_price = adverse


def _track_post_target_1(s: SuggestionState, events: list[EngineEvent], at: dt.datetime, adverse: float, source: str) -> None:
    """Breakeven-after-T1 study data: worst price after target 1 and the
    first time price came back to the entry. Records only -- the original
    stop is never moved."""
    if s.post_target_1_adverse_price is None or _more_favorable(s, s.post_target_1_adverse_price, adverse):
        s.post_target_1_adverse_price = adverse
    if s.breakeven_revisited_after_target_1_at is None and _adv_reached(s, adverse, s.entry_triggered_price):
        s.breakeven_revisited_after_target_1_at = at
        events.append(EngineEvent(
            event_type=E.BREAKEVEN_REVISITED_AFTER_TARGET_1.value, from_status=s.status, to_status=s.status,
            observed_at=at, threshold_price=s.entry_triggered_price, observed_market_price=adverse,
            observed_price_basis=B.TICK.value if source == ObservationSource.TICK.value else B.WITHIN_BAR_RANGE.value,
            data_source=source, detail={"study_only": True, "stop_unchanged": s.stop_loss},
        ))


def _refresh_derived(s: SuggestionState) -> None:
    entry = s.entry_triggered_price
    if entry is None:
        return
    if s.max_favorable_price is not None:
        s.max_favorable_excursion = _return_pct(s, entry, s.max_favorable_price)
    if s.max_adverse_price is not None:
        s.max_adverse_excursion = _return_pct(s, entry, s.max_adverse_price)
    if s.status in TERMINAL_STATUSES:
        if s.close_price is not None:
            s.realized_or_marked_return_pct = _return_pct(s, entry, s.close_price)
            s.return_is_realized = True
    elif s.last_observed_price is not None:
        s.realized_or_marked_return_pct = _return_pct(s, entry, s.last_observed_price)
        s.return_is_realized = False


# ---- public API ----------------------------------------------------------------------


def apply_tick(state: SuggestionState, tick: Tick) -> tuple[SuggestionState, list[EngineEvent]]:
    s = copy.deepcopy(state)
    events: list[EngineEvent] = []
    if s.status in TERMINAL_STATUSES or tick.at <= s.generated_at:
        return s, events

    p = tick.price
    s.last_observed_price, s.last_observed_at = p, tick.at

    if s.status == S.WAITING_ENTRY:
        inv = _pre_entry_invalidation(s)
        if _adv_reached(s, p, inv):
            _transition(s, events, S.INVALIDATED, E.INVALIDATED, tick.at, inv, p, B.TICK, tick.source)
        elif _in_zone(s, p):
            _enter(s, events, tick.at, p, B.TICK, tick.source)
        _refresh_derived(s)
        return s, events

    _update_excursions(s, p, p)
    if s.status == S.TARGET_1_HIT:
        _track_post_target_1(s, events, tick.at, p, tick.source)

    if _adv_reached(s, p, s.stop_loss):
        _hit_stop(s, events, tick.at, p, B.TICK, tick.source)
    else:
        if s.status == S.ACTIVE and _fav_reached(s, p, s.target_1):
            _hit_target_1(s, events, tick.at, p, B.TICK, tick.source)
        if s.status == S.TARGET_1_HIT and s.target_2 is not None and _fav_reached(s, p, s.target_2):
            _hit_target_2(s, events, tick.at, p, B.TICK, tick.source)

    _refresh_derived(s)
    return s, events


def _apply_entry_bar(s: SuggestionState, events: list[EngineEvent], bar: Bar) -> None:
    """The bar in which entry happens. Which parts of the bar are post-entry
    depends on where it opened relative to the zone:
      INSIDE    entry at the open, so the whole bar is post-entry.
      FAVORABLE price came back to the zone from the target side: the stop
                side of the bar is post-entry (price had to pass the zone to
                get there); a target touch may have happened BEFORE entry.
      ADVERSE   price rose/fell into the zone from the stop side: the target
                side is post-entry; a stop touch may have happened BEFORE entry.
    """
    side = _zone_side(s, bar.open)
    if side == "INSIDE":
        _enter(s, events, bar.start, bar.open, B.OPEN_IN_ZONE, bar.source)
        _apply_position_bar(s, events, bar, skip_gap_checks=True)
        return

    entry_price = min(max(bar.open, s.entry_low), s.entry_high)  # the zone edge price travelled through
    _enter(s, events, bar.end, entry_price, B.WITHIN_BAR_RANGE, bar.source)

    stop_touched = _adv_reached(s, _adv_extreme(s, bar), s.stop_loss)
    t1_touched = _fav_reached(s, _fav_extreme(s, bar), s.target_1)
    t2_touched = s.target_2 is not None and _fav_reached(s, _fav_extreme(s, bar), s.target_2)

    if side == "FAVORABLE":
        _update_excursions(s, None, _adv_extreme(s, bar))  # adverse side is post-entry; favorable is not
        if stop_touched:
            _hit_stop(
                s, events, bar.end, s.stop_loss, B.WITHIN_BAR_RANGE, bar.source, ambiguous=t1_touched,
                detail={"reason": "entry and stop in the same bar; a target touch in this bar may precede entry",
                        "target_1_touched_in_bar": t1_touched} if t1_touched else None,
            )
        elif t1_touched:
            # The target touch may have happened before price came back to
            # the zone: not credited, and the entry event says so.
            s.ambiguous_bar = True
            entry_event = events[-1]
            events[-1] = dataclasses.replace(
                entry_event, ambiguous_bar=True,
                detail={**entry_event.detail,
                        "note": "target 1 touched in the entry bar but may have preceded entry -- not credited"},
            )
        return

    # side == "ADVERSE": target side is post-entry, stop side is ambiguous.
    _update_excursions(s, _fav_extreme(s, bar), None)
    if stop_touched:
        # Stop may have been touched BEFORE entry (-> invalidated) or after
        # (-> failed). Conservative: count it as a failed trade.
        _hit_stop(
            s, events, bar.end, s.stop_loss, B.WITHIN_BAR_RANGE, bar.source, ambiguous=True,
            detail={"reason": "bar opened on the stop side of the zone and touched both zone and stop; "
                              "ordering unknown -- conservative stop-first",
                    "target_1_touched_in_bar": t1_touched},
        )
        _update_excursions(s, None, s.stop_loss)
        return
    if t1_touched:
        _hit_target_1(s, events, bar.end, s.target_1, B.WITHIN_BAR_RANGE, bar.source)
        if t2_touched:
            _hit_target_2(s, events, bar.end, s.target_2, B.WITHIN_BAR_RANGE, bar.source)


def _apply_position_bar(s: SuggestionState, events: list[EngineEvent], bar: Bar, skip_gap_checks: bool = False) -> None:
    """A bar that is entirely post-entry."""
    t1_known_before_bar = s.status == S.TARGET_1_HIT

    if not skip_gap_checks:
        o = bar.open
        if _adv_reached(s, o, s.stop_loss):
            _update_excursions(s, None, o)
            if t1_known_before_bar:
                _track_post_target_1(s, events, bar.start, o, bar.source)
            _hit_stop(s, events, bar.start, o, B.GAP_OPEN, bar.source)
            return
        if s.status == S.ACTIVE and _fav_reached(s, o, s.target_1):
            _update_excursions(s, o, None)
            _hit_target_1(s, events, bar.start, o, B.GAP_OPEN, bar.source)
            t1_known_before_bar = True  # the open is the first price: T1 precedes the rest of the bar
        if s.status == S.TARGET_1_HIT and s.target_2 is not None and _fav_reached(s, o, s.target_2):
            _update_excursions(s, o, None)
            _hit_target_2(s, events, bar.start, o, B.GAP_OPEN, bar.source)
            return

    fav, adv = _fav_extreme(s, bar), _adv_extreme(s, bar)
    stop_touched = _adv_reached(s, adv, s.stop_loss)
    t1_touched = s.status == S.ACTIVE and _fav_reached(s, fav, s.target_1)
    t2_touched = s.target_2 is not None and _fav_reached(s, fav, s.target_2)

    if t1_known_before_bar:
        _track_post_target_1(s, events, bar.end, adv, bar.source)

    if stop_touched and (t1_touched or t2_touched):
        # Ordering inside the bar is unknown: conservative stop-first. The
        # favorable extreme is not credited to MFE since it may postdate the exit.
        _update_excursions(s, None, adv)
        _hit_stop(
            s, events, bar.end, s.stop_loss, B.WITHIN_BAR_RANGE, bar.source, ambiguous=True,
            detail={"reason": "same bar touched stop and target; ordering unknown -- conservative stop-first",
                    "target_1_touched_in_bar": t1_touched, "target_2_touched_in_bar": t2_touched,
                    "bar": {"open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close}},
        )
        return

    _update_excursions(s, fav, adv)
    if stop_touched:
        _hit_stop(s, events, bar.end, s.stop_loss, B.WITHIN_BAR_RANGE, bar.source)
        return
    if t1_touched:
        _hit_target_1(s, events, bar.end, s.target_1, B.WITHIN_BAR_RANGE, bar.source)
    if s.status == S.TARGET_1_HIT and t2_touched:
        _hit_target_2(s, events, bar.end, s.target_2, B.WITHIN_BAR_RANGE, bar.source)


def apply_bar(state: SuggestionState, bar: Bar) -> tuple[SuggestionState, list[EngineEvent]]:
    s = copy.deepcopy(state)
    events: list[EngineEvent] = []
    if s.status in TERMINAL_STATUSES:
        return s, events
    if bar.start < s.generated_at:
        # Mixes pre-generation prices: cannot establish a post-creation touch.
        return s, events
    if s.status != S.WAITING_ENTRY and s.entry_triggered_at is not None and bar.start < s.entry_triggered_at:
        # Contains pre-entry prices; outcome thresholds only count post-entry.
        return s, events

    s.last_observed_price, s.last_observed_at = bar.close, bar.end

    if s.status == S.WAITING_ENTRY:
        inv = _pre_entry_invalidation(s)
        if _adv_reached(s, bar.open, inv):
            _transition(s, events, S.INVALIDATED, E.INVALIDATED, bar.start, inv, bar.open, B.GAP_OPEN, bar.source)
        elif bar.low <= s.entry_high and bar.high >= s.entry_low:
            _apply_entry_bar(s, events, bar)
        elif _adv_reached(s, _adv_extreme(s, bar), inv):
            _transition(s, events, S.INVALIDATED, E.INVALIDATED, bar.end, inv, inv, B.WITHIN_BAR_RANGE, bar.source)
    else:
        _apply_position_bar(s, events, bar)

    _refresh_derived(s)
    return s, events


def on_session_close(
    state: SuggestionState, session_date: dt.date, close_price: float | None, closed_at: dt.datetime,
    source: str = ObservationSource.CANDLE_D.value,
) -> tuple[SuggestionState, list[EngineEvent]]:
    """Session-count deadlines. Apply AFTER all of the session's price
    observations have been applied."""
    s = copy.deepcopy(state)
    events: list[EngineEvent] = []
    if s.status == S.WAITING_ENTRY:
        if s.entry_deadline_session_date is not None and session_date >= s.entry_deadline_session_date:
            _transition(
                s, events, S.NO_ENTRY, E.NO_ENTRY, closed_at, None, close_price, B.SESSION_CLOSE, source,
                detail={"entry_deadline_session_date": s.entry_deadline_session_date.isoformat()},
            )
    elif s.status in OPEN_STATUSES:
        if s.holding_deadline_session_date is not None and session_date >= s.holding_deadline_session_date:
            if close_price is None:
                raise ValueError("A real session close price is required to expire an active suggestion")
            s.last_observed_price, s.last_observed_at = close_price, closed_at
            _transition(
                s, events, S.EXPIRED, E.EXPIRED, closed_at, None, close_price, B.SESSION_CLOSE, source,
                detail={"holding_deadline_session_date": s.holding_deadline_session_date.isoformat()},
            )
    _refresh_derived(s)
    return s, events


def exit_before_close(
    state: SuggestionState, at: dt.datetime, last_price: float | None, source: str,
) -> tuple[SuggestionState, list[EngineEvent]]:
    """Intraday cutoff: an open position exits at the latest legitimate
    price; an untriggered suggestion becomes NO_ENTRY."""
    s = copy.deepcopy(state)
    events: list[EngineEvent] = []
    if s.status == S.WAITING_ENTRY:
        _transition(s, events, S.NO_ENTRY, E.NO_ENTRY, at, None, last_price, B.LAST_OBSERVED, source,
                    detail={"reason": "session cutoff reached before entry"})
    elif s.status in OPEN_STATUSES:
        if last_price is None:
            raise ValueError("A real last price is required to close an active suggestion at the cutoff")
        s.last_observed_price, s.last_observed_at = last_price, at
        _transition(s, events, S.EXIT_BEFORE_CLOSE, E.EXIT_BEFORE_CLOSE, at, None, last_price, B.LAST_OBSERVED, source)
    _refresh_derived(s)
    return s, events


def cancel(state: SuggestionState, at: dt.datetime, reason: str) -> tuple[SuggestionState, list[EngineEvent]]:
    s = copy.deepcopy(state)
    events: list[EngineEvent] = []
    if s.status in OPEN_STATUSES:
        s.failure_reason = reason[:512]
        observed = s.last_observed_price if s.entry_triggered_price is not None else None
        _transition(s, events, S.CANCELLED, E.CANCELLED, at, None, observed,
                    B.LAST_OBSERVED if observed is not None else None, ObservationSource.MANUAL.value,
                    detail={"reason": reason[:512]})
    _refresh_derived(s)
    return s, events
