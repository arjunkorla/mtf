"""Suggestion tracker service foundation (Phase A).

Persists scanner recommendations as TradeSuggestion rows and applies market
observations through the pure state engine (suggestion_state_engine.py),
appending every transition to the append-only TradeSuggestionEvent log.

Not wired to any scanner yet (MTF integration is a separately approved
phase) and makes no FYERS calls: callers supply real observations.
"""

import dataclasses
import datetime as dt
import decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.suggestion_constants import (
    OPEN_STATUSES,
    CreationStatus,
    EntryRule,
    ScannerType,
    SuggestionEventType,
    SuggestionOutcome,
    SuggestionStatus,
)
from app.data.session_calendar import nth_nse_session_after
from app.engines import suggestion_state_engine as engine
from app.engines.suggestion_level_validation import LevelSpec, validate_levels
from app.logging_config import get_logger
from app.models.trade_suggestion import TradeSuggestion
from app.models.trade_suggestion_event import TradeSuggestionEvent
from app.schemas.suggestion import CreationResult, SuggestionCreateRequest

logger = get_logger(__name__)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# Critical-data states that must never produce an actionable suggestion.
UNUSABLE_DATA_QUALITY = frozenset({"UNAVAILABLE", "INSUFFICIENT_DATA", "STALE"})
UNUSABLE_MARKET_STATUS = frozenset({"UNAVAILABLE", "STALE"})


@dataclasses.dataclass(frozen=True)
class LifecycleRules:
    entry_window_sessions: int
    max_holding_sessions: int


def lifecycle_rules(scanner_type: str, settings: Settings | None = None) -> LifecycleRules | None:
    """Only MTF has approved rules so far. Intraday/MCX lifecycles (session
    cutoffs, MCX calendar) are defined in their own later phases."""
    settings = settings or get_settings()
    if scanner_type == ScannerType.MTF.value:
        return LifecycleRules(
            entry_window_sessions=settings.suggestion_mtf_entry_window_sessions,
            max_holding_sessions=settings.suggestion_mtf_max_holding_sessions,
        )
    return None


def build_dedup_key(scanner_type: str, symbol: str, direction: str, coexistence_group: str) -> str:
    return f"{scanner_type}|{symbol}|{direction}|{coexistence_group}"


def _ist_date(ts: dt.datetime) -> dt.date:
    return ts.astimezone(IST).date()


def _f(value) -> float | None:
    return float(value) if value is not None else None


async def _next_sequence(db: AsyncSession, suggestion_id: int) -> int:
    current = (
        await db.execute(
            select(func.max(TradeSuggestionEvent.sequence)).where(TradeSuggestionEvent.suggestion_id == suggestion_id)
        )
    ).scalar()
    return (current or 0) + 1


async def _append_event(db: AsyncSession, suggestion_id: int, ev: engine.EngineEvent) -> TradeSuggestionEvent:
    row = TradeSuggestionEvent(
        suggestion_id=suggestion_id,
        sequence=await _next_sequence(db, suggestion_id),
        event_type=ev.event_type,
        from_status=ev.from_status,
        to_status=ev.to_status,
        threshold_price=ev.threshold_price,
        observed_market_price=ev.observed_market_price,
        observed_price_basis=ev.observed_price_basis,
        observed_at=ev.observed_at,
        data_source=ev.data_source,
        ambiguous_bar=ev.ambiguous_bar,
        detail=_jsonable(ev.detail),
    )
    db.add(row)
    await db.flush()
    return row


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):  # Numeric DB columns (e.g. research scores, VIX)
        return float(value)
    return value


async def find_open_duplicate(db: AsyncSession, dedup_key: str) -> TradeSuggestion | None:
    return (
        await db.execute(select(TradeSuggestion).where(TradeSuggestion.open_dedup_key == dedup_key))
    ).scalar_one_or_none()


async def _log_repeat(db: AsyncSession, existing: TradeSuggestion, request: SuggestionCreateRequest) -> None:
    """A repeated scanner signal is evidence against the open suggestion,
    not a new trade. The original snapshot/levels are never overwritten."""
    await _append_event(db, existing.id, engine.EngineEvent(
        event_type=SuggestionEventType.SIGNAL_REPEATED.value,
        from_status=existing.status, to_status=existing.status,
        observed_at=request.generated_at, observed_market_price=request.generation_market_price,
        data_source=request.generation_price_source,
        detail={
            "scanner_run_id": request.scanner_run_id, "setup_type": request.setup_type, "score": request.score,
            "confidence": request.confidence, "market_status": request.market_status,
            "data_quality": request.data_quality,
            "levels": {k: v.model_dump() for k, v in request.levels.items()},
        },
    ))


async def create_suggestion(
    db: AsyncSession, request: SuggestionCreateRequest, settings: Settings | None = None,
) -> CreationResult:
    settings = settings or get_settings()

    # 1. Critical data gate -- never a suggestion from stale/unavailable data.
    dq_reasons = []
    if request.generation_market_price is None or request.generation_market_price <= 0:
        dq_reasons.append("generation market price is unavailable")
    if request.data_quality in UNUSABLE_DATA_QUALITY:
        dq_reasons.append(f"data_quality is {request.data_quality}")
    if request.market_status in UNUSABLE_MARKET_STATUS:
        dq_reasons.append(f"market_status is {request.market_status}")
    if request.generated_at.tzinfo is None:
        dq_reasons.append("generated_at must be timezone-aware")
    if dq_reasons:
        return CreationResult(status=CreationStatus.REJECTED_DATA_QUALITY, reasons=dq_reasons)

    # 2. Lifecycle rules must exist for this scanner.
    rules = lifecycle_rules(request.scanner_type, settings)
    if rules is None:
        return CreationResult(
            status=CreationStatus.REJECTED_NO_LIFECYCLE_RULES,
            reasons=[f"no approved lifecycle rules for scanner_type {request.scanner_type}"],
        )

    # 3. Level quality -- FALLBACK/UNAVAILABLE levels never become trade levels.
    validation = validate_levels(
        request.direction,
        {name: LevelSpec(price=spec.price, quality=spec.quality, provenance=spec.provenance)
         for name, spec in request.levels.items()},
    )
    if not validation.accepted:
        return CreationResult(status=CreationStatus.REJECTED_LEVELS, reasons=validation.reasons, notes=validation.notes)
    lv = validation.levels

    # 4. Duplicate prevention.
    dedup_key = build_dedup_key(request.scanner_type, request.symbol, request.direction, request.coexistence_group)
    existing = await find_open_duplicate(db, dedup_key)
    if existing is not None:
        await _log_repeat(db, existing, request)
        await db.commit()
        return CreationResult(status=CreationStatus.DUPLICATE_OPEN, suggestion_id=existing.id,
                              reasons=["an equivalent open suggestion already exists"])

    generation_session = _ist_date(request.generated_at)
    entry_deadline, calendar_verified = nth_nse_session_after(generation_session, rules.entry_window_sessions)
    gen_price = float(request.generation_market_price)
    if lv["entry_low"] <= gen_price <= lv["entry_high"]:
        zone_position = "INSIDE"
    else:
        zone_position = "ABOVE" if gen_price > lv["entry_high"] else "BELOW"

    row = TradeSuggestion(
        scanner_type=request.scanner_type, market=request.market, symbol=request.symbol,
        underlying_symbol=request.underlying_symbol, instrument_type=request.instrument_type,
        direction=request.direction, setup_type=request.setup_type,
        coexistence_group=request.coexistence_group, open_dedup_key=dedup_key,
        scanner_run_id=request.scanner_run_id,
        generated_at=request.generated_at, generation_session_date=generation_session,
        generation_market_price=gen_price, generation_price_source=request.generation_price_source,
        generation_price_zone_position=zone_position,
        market_status=request.market_status, data_quality=request.data_quality,
        entry_rule=EntryRule.FRESH_TOUCH_AFTER_CREATION.value,
        entry_low=lv["entry_low"], entry_high=lv["entry_high"], reference_entry_price=request.reference_entry_price,
        target_1=lv["target_1"], target_2=lv["target_2"], stop_loss=lv["stop_loss"],
        invalidation_price=lv["invalidation_price"],
        level_quality=validation.level_quality, level_notes=validation.notes,
        suggested_holding_period=request.suggested_holding_period,
        entry_window_sessions=rules.entry_window_sessions, max_holding_sessions=rules.max_holding_sessions,
        entry_deadline_session_date=entry_deadline, session_calendar_verified=calendar_verified,
        expires_at=request.expires_at, score=request.score, confidence=request.confidence,
        option_symbol=request.option_symbol, option_strike=request.option_strike,
        option_type=request.option_type, option_expiry=request.option_expiry,
        status=SuggestionStatus.WAITING_ENTRY.value, outcome=SuggestionOutcome.PENDING.value,
        evidence_snapshot=_jsonable(request.evidence_snapshot), research_metadata=_jsonable(request.research_metadata),
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        # Lost a race with a concurrent creator for the same key: log
        # against the winner instead of creating a duplicate.
        await db.rollback()
        existing = await find_open_duplicate(db, dedup_key)
        if existing is None:
            raise
        await _log_repeat(db, existing, request)
        await db.commit()
        return CreationResult(status=CreationStatus.DUPLICATE_OPEN, suggestion_id=existing.id,
                              reasons=["an equivalent open suggestion already exists"])

    await _append_event(db, row.id, engine.EngineEvent(
        event_type=SuggestionEventType.SUGGESTION_CREATED.value, from_status=None,
        to_status=SuggestionStatus.WAITING_ENTRY.value, observed_at=request.generated_at,
        observed_market_price=gen_price, data_source=request.generation_price_source,
        detail={"generation_price_zone_position": zone_position, "entry_rule": row.entry_rule,
                "entry_deadline_session_date": entry_deadline.isoformat(),
                "session_calendar_verified": calendar_verified, "level_notes": validation.notes},
    ))
    await db.commit()
    return CreationResult(status=CreationStatus.CREATED, suggestion_id=row.id, notes=validation.notes)


# ---- tracking ------------------------------------------------------------------------


def state_from_row(row: TradeSuggestion) -> engine.SuggestionState:
    return engine.SuggestionState(
        direction=row.direction, entry_low=_f(row.entry_low), entry_high=_f(row.entry_high),
        target_1=_f(row.target_1), target_2=_f(row.target_2), stop_loss=_f(row.stop_loss),
        invalidation_price=_f(row.invalidation_price), generated_at=_aware(row.generated_at),
        entry_deadline_session_date=row.entry_deadline_session_date,
        holding_deadline_session_date=row.holding_deadline_session_date,
        status=row.status, outcome=row.outcome,
        entry_triggered_at=_aware(row.entry_triggered_at), entry_triggered_price=_f(row.entry_triggered_price),
        target_1_hit_at=_aware(row.target_1_hit_at), target_1_hit_price=_f(row.target_1_hit_price),
        target_2_hit_at=_aware(row.target_2_hit_at), target_2_hit_price=_f(row.target_2_hit_price),
        stop_hit_at=_aware(row.stop_hit_at), stop_hit_price=_f(row.stop_hit_price),
        closed_at=_aware(row.closed_at), close_price=_f(row.close_price),
        max_favorable_price=_f(row.max_favorable_price), max_adverse_price=_f(row.max_adverse_price),
        max_favorable_excursion=_f(row.max_favorable_excursion), max_adverse_excursion=_f(row.max_adverse_excursion),
        realized_or_marked_return_pct=_f(row.realized_or_marked_return_pct),
        return_is_realized=bool(row.return_is_realized),
        post_target_1_adverse_price=_f(row.post_target_1_adverse_price),
        breakeven_revisited_after_target_1_at=_aware(row.breakeven_revisited_after_target_1_at),
        ambiguous_bar=bool(row.ambiguous_bar), failure_reason=row.failure_reason,
        last_observed_price=_f(row.last_observed_price), last_observed_at=_aware(row.last_observed_at),
    )


def _aware(ts: dt.datetime | None) -> dt.datetime | None:
    # SQLite (tests) drops tzinfo; PostgreSQL keeps it. All stored times are UTC.
    if ts is None:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=dt.UTC)


async def _persist_state(
    db: AsyncSession, row: TradeSuggestion, state: engine.SuggestionState, events: list[engine.EngineEvent],
) -> None:
    was_waiting = row.status == SuggestionStatus.WAITING_ENTRY.value
    had_holding_deadline = row.holding_deadline_session_date is not None
    for name in engine.MUTABLE_STATE_FIELDS:
        setattr(row, name, getattr(state, name))

    # Checked against the row's value BEFORE the copy above: a caller (the
    # tracker) may already carry the deadline in its working state, and the
    # calendar-coverage flag must still be recorded in that case.
    if was_waiting and state.entry_triggered_at is not None and not had_holding_deadline:
        deadline, verified = nth_nse_session_after(_ist_date(state.entry_triggered_at), row.max_holding_sessions)
        row.holding_deadline_session_date = deadline
        if not verified:
            row.session_calendar_verified = False

    if row.status not in {s.value for s in OPEN_STATUSES}:
        row.open_dedup_key = None  # frees the key: a new equivalent suggestion may now be created
    row.last_evaluated_at = dt.datetime.now(dt.UTC)

    for ev in events:
        await _append_event(db, row.id, ev)


async def apply_observations(
    db: AsyncSession, suggestion_id: int, observations: list[engine.Tick | engine.Bar],
) -> list[engine.EngineEvent]:
    """Applies real, time-ordered observations. Holding deadlines are set as
    soon as entry happens so a later session close can expire correctly."""
    row = await db.get(TradeSuggestion, suggestion_id)
    if row is None:
        raise LookupError(f"suggestion {suggestion_id} not found")

    all_events: list[engine.EngineEvent] = []
    for obs in sorted(observations, key=lambda o: o.at if isinstance(o, engine.Tick) else o.start):
        state = state_from_row(row)
        if isinstance(obs, engine.Tick):
            state, events = engine.apply_tick(state, obs)
        else:
            state, events = engine.apply_bar(state, obs)
        await _persist_state(db, row, state, events)
        all_events.extend(events)
    await db.commit()
    return all_events


async def apply_session_close(
    db: AsyncSession, suggestion_id: int, session_date: dt.date, close_price: float | None,
    closed_at: dt.datetime, source: str,
) -> list[engine.EngineEvent]:
    row = await db.get(TradeSuggestion, suggestion_id)
    if row is None:
        raise LookupError(f"suggestion {suggestion_id} not found")
    state, events = engine.on_session_close(state_from_row(row), session_date, close_price, closed_at, source)
    await _persist_state(db, row, state, events)
    await db.commit()
    return events


async def cancel_suggestion(db: AsyncSession, suggestion_id: int, reason: str) -> list[engine.EngineEvent]:
    row = await db.get(TradeSuggestion, suggestion_id)
    if row is None:
        raise LookupError(f"suggestion {suggestion_id} not found")
    state, events = engine.cancel(state_from_row(row), dt.datetime.now(dt.UTC), reason)
    await _persist_state(db, row, state, events)
    await db.commit()
    return events


async def list_events(db: AsyncSession, suggestion_id: int) -> list[TradeSuggestionEvent]:
    return list((
        await db.execute(
            select(TradeSuggestionEvent).where(TradeSuggestionEvent.suggestion_id == suggestion_id)
            .order_by(TradeSuggestionEvent.sequence)
        )
    ).scalars().all())


async def list_suggestions(
    db: AsyncSession, since: dt.datetime | None = None, scanner_type: str | None = None,
    statuses: list[str] | None = None, limit: int = 500,
) -> list[TradeSuggestion]:
    """History query. Nothing is ever deleted -- `since` only narrows the
    view (the future History page defaults to the last 7 days)."""
    stmt = select(TradeSuggestion).order_by(TradeSuggestion.generated_at.desc()).limit(limit)
    if since is not None:
        stmt = stmt.where(TradeSuggestion.generated_at >= since)
    if scanner_type is not None:
        stmt = stmt.where(TradeSuggestion.scanner_type == scanner_type)
    if statuses:
        stmt = stmt.where(TradeSuggestion.status.in_(statuses))
    return list((await db.execute(stmt)).scalars().all())


# ---- tracker persistence (Phase B) ------------------------------------------------------


TRACKER_OWNED_COLUMNS = frozenset({"max_favorable_at", "max_adverse_at", "max_adverse_price_before_target_1"})


class TrackingConflict(RuntimeError):
    """The row changed (new events) since the tracker loaded it: the
    tracker's working state is discarded and rebuilt from the database."""


async def current_sequence(db: AsyncSession, suggestion_id: int) -> int:
    return await _next_sequence(db, suggestion_id) - 1


async def load_open_suggestions(db: AsyncSession) -> list[TradeSuggestion]:
    stmt = (
        select(TradeSuggestion)
        .where(TradeSuggestion.status.in_([s.value for s in OPEN_STATUSES]))
        .order_by(TradeSuggestion.id)
        .execution_options(populate_existing=True)
    )
    return list((await db.execute(stmt)).scalars().all())


async def commit_tracking_update(
    db: AsyncSession, suggestion_id: int, state: engine.SuggestionState, events: list[engine.EngineEvent],
    reconciled_through: dt.datetime | None, tracking_status: str, tracking_status_reason: str | None,
    expected_sequence: int,
    extra: dict | None = None,
) -> int:
    """Persists the tracker's working state + new events in ONE transaction,
    together with the reconciliation watermark -- so a restart re-applies
    exactly the candles after the watermark and never duplicates an event.

    Optimistic guard: if anyone appended an event since the tracker loaded
    the row (sequence moved), nothing is written and TrackingConflict is
    raised. Returns the new last event sequence."""
    row = (
        await db.execute(
            select(TradeSuggestion).where(TradeSuggestion.id == suggestion_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"suggestion {suggestion_id} not found")
    if await current_sequence(db, suggestion_id) != expected_sequence:
        await db.rollback()
        raise TrackingConflict(f"suggestion {suggestion_id} changed since it was loaded")
    try:
        await _persist_state(db, row, state, events)
        row.reconciled_through = reconciled_through
        row.tracking_status = tracking_status
        row.tracking_status_reason = tracking_status_reason[:256] if tracking_status_reason else None
        for name, value in (extra or {}).items():
            if name not in TRACKER_OWNED_COLUMNS:
                raise ValueError(f"{name} is not a tracker-owned column")
            setattr(row, name, value)
        await db.commit()
    except IntegrityError as exc:  # a concurrent writer took the same sequence number
        await db.rollback()
        raise TrackingConflict(f"suggestion {suggestion_id}: concurrent event append") from exc
    return expected_sequence + len(events)


async def set_tracking_status(db: AsyncSession, suggestion_ids: list[int], status: str, reason: str | None) -> int:
    """Marks tracking health only (e.g. AUTH_REQUIRED). Never touches
    lifecycle status/outcome or any generation-time field."""
    if not suggestion_ids:
        return 0
    result = await db.execute(
        update(TradeSuggestion)
        .where(TradeSuggestion.id.in_(suggestion_ids))
        .where(TradeSuggestion.status.in_([s.value for s in OPEN_STATUSES]))
        .values(tracking_status=status, tracking_status_reason=reason[:256] if reason else None)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return result.rowcount or 0


# ---- read API queries (Phase B) ---------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SuggestionFilters:
    scanner_type: str | None = None
    market: str | None = None
    status: list[str] | None = None
    outcome: list[str] | None = None
    symbol: str | None = None
    direction: str | None = None
    generated_from: dt.datetime | None = None
    generated_to: dt.datetime | None = None


def _apply_filters(stmt, f: SuggestionFilters):
    if f.scanner_type:
        stmt = stmt.where(TradeSuggestion.scanner_type == f.scanner_type)
    if f.market:
        stmt = stmt.where(TradeSuggestion.market == f.market)
    if f.status:
        stmt = stmt.where(TradeSuggestion.status.in_(f.status))
    if f.outcome:
        stmt = stmt.where(TradeSuggestion.outcome.in_(f.outcome))
    if f.symbol:
        stmt = stmt.where(TradeSuggestion.symbol == f.symbol)
    if f.direction:
        stmt = stmt.where(TradeSuggestion.direction == f.direction)
    if f.generated_from is not None:
        stmt = stmt.where(TradeSuggestion.generated_at >= f.generated_from)
    if f.generated_to is not None:
        stmt = stmt.where(TradeSuggestion.generated_at < f.generated_to)
    return stmt


async def query_suggestions(
    db: AsyncSession, filters: SuggestionFilters, limit: int, offset: int,
) -> tuple[list[TradeSuggestion], int]:
    total = (await db.execute(_apply_filters(select(func.count(TradeSuggestion.id)), filters))).scalar() or 0
    stmt = _apply_filters(select(TradeSuggestion), filters).order_by(
        TradeSuggestion.generated_at.desc(), TradeSuggestion.id.desc()
    ).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total


async def get_suggestion(db: AsyncSession, suggestion_id: int) -> TradeSuggestion | None:
    return await db.get(TradeSuggestion, suggestion_id)


# Outcomes of a TRIGGERED trade that reached a market-determined end. These
# (and only these) form the win-rate denominator. NO_ENTRY and
# INVALIDATED_BEFORE_ENTRY never had a position; CANCELLED is an operator
# action, not a market result.
COMPLETED_TRADE_OUTCOMES = frozenset({
    SuggestionOutcome.SUCCESS_TARGET_2.value,
    SuggestionOutcome.SUCCESS_TARGET_1.value,
    SuggestionOutcome.PARTIAL_SUCCESS.value,
    SuggestionOutcome.FAILED_STOP.value,
    SuggestionOutcome.EXPIRED.value,
    SuggestionOutcome.EXIT_BEFORE_CLOSE.value,
})
WIN_OUTCOMES = frozenset({SuggestionOutcome.SUCCESS_TARGET_2.value, SuggestionOutcome.SUCCESS_TARGET_1.value})
LOSS_OUTCOMES = frozenset({SuggestionOutcome.FAILED_STOP.value})


def wilson_interval(successes: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    """95% Wilson score interval for a proportion -- reported so a small
    sample's uncertainty is visible, not hidden behind a single percentage."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return round(max(0.0, centre - half) * 100, 2), round(min(1.0, centre + half) * 100, 2)


def _minutes(a: dt.datetime | None, b: dt.datetime | None) -> float | None:
    a, b = _aware(a), _aware(b)
    return round((b - a).total_seconds() / 60, 1) if a is not None and b is not None else None


def _sessions_between(a: dt.datetime | None, b: dt.datetime | None) -> int | None:
    """NSE sessions strictly after a's IST date up to and including b's
    (0 = same session). Beyond the verified holiday year it is weekday-only
    -- the row's session_calendar_verified flag says so."""
    from app.data.nse_holidays import is_nse_trading_day

    a, b = _aware(a), _aware(b)
    if a is None or b is None:
        return None
    d, end, n = _ist_date(a), _ist_date(b), 0
    while d < end:
        d += dt.timedelta(days=1)
        n += is_nse_trading_day(d)
    return n


async def performance_summary(db: AsyncSession, filters: SuggestionFilters) -> dict:
    rows = (
        await db.execute(
            _apply_filters(
                select(
                    TradeSuggestion.status, TradeSuggestion.outcome, TradeSuggestion.entry_triggered_at,
                    TradeSuggestion.realized_or_marked_return_pct, TradeSuggestion.return_is_realized,
                    TradeSuggestion.ambiguous_bar,
                ),
                filters,
            )
        )
    ).all()

    by_status = {s.value: 0 for s in SuggestionStatus}
    by_outcome = {o.value: 0 for o in SuggestionOutcome}
    triggered = completed = wins = losses = partial = expired_trades = ambiguous_completed = 0
    realized_returns: list[float] = []
    for status, outcome, entry_at, ret, realized, ambiguous in rows:
        by_status[status] = by_status.get(status, 0) + 1
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if entry_at is None:
            continue
        triggered += 1
        if outcome not in COMPLETED_TRADE_OUTCOMES:
            continue
        completed += 1
        if outcome in WIN_OUTCOMES:
            wins += 1
        elif outcome in LOSS_OUTCOMES:
            losses += 1
        elif outcome == SuggestionOutcome.PARTIAL_SUCCESS.value:
            partial += 1
        else:
            expired_trades += 1
        if ambiguous:
            ambiguous_completed += 1
        if realized and ret is not None:
            realized_returns.append(float(ret))

    def pct(n: int) -> float | None:
        return round(n / completed * 100, 2) if completed else None

    return {
        "total_suggestions": len(rows),
        "counts": {
            "waiting_entry": by_status[SuggestionStatus.WAITING_ENTRY.value],
            "active": by_status[SuggestionStatus.ACTIVE.value],
            "target_1_hit": by_status[SuggestionStatus.TARGET_1_HIT.value],
            "target_2_hit": by_status[SuggestionStatus.TARGET_2_HIT.value],
            "stop_hit": by_status[SuggestionStatus.STOP_HIT.value],
            "no_entry": by_status[SuggestionStatus.NO_ENTRY.value],
            "invalidated": by_status[SuggestionStatus.INVALIDATED.value],
            "expired": by_status[SuggestionStatus.EXPIRED.value],
            "exit_before_close": by_status[SuggestionStatus.EXIT_BEFORE_CLOSE.value],
            "cancelled": by_status[SuggestionStatus.CANCELLED.value],
        },
        "by_status": by_status,
        "by_outcome": by_outcome,
        "triggered_trades": triggered,
        "completed_trades": completed,
        "open_trades": by_status[SuggestionStatus.ACTIVE.value] + by_status[SuggestionStatus.TARGET_1_HIT.value],
        "wins": wins,
        "losses": losses,
        "partial_successes": partial,
        "expired_without_target": expired_trades,
        "ambiguous_completed_trades": ambiguous_completed,
        "sample_size": completed,
        "win_rate_pct": pct(wins),
        "win_rate_95ci_pct": wilson_interval(wins, completed),
        "loss_rate_pct": pct(losses),
        "partial_success_rate_pct": pct(partial),
        "target_1_reached_rate_pct": pct(wins + partial),
        "avg_realized_return_pct": (
            round(sum(realized_returns) / len(realized_returns), 4) if realized_returns else None
        ),
        "realized_return_sample_size": len(realized_returns),
    }
