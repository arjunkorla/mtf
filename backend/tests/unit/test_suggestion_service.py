"""Phase A: suggestion persistence, level-quality gate, duplicate prevention,
append-only events, immutable snapshots. SQLite in-memory (conftest
db_session); no FYERS calls."""

import datetime as dt

import pytest
from sqlalchemy import func, select

from app.core.suggestion_constants import (
    CreationStatus,
    LevelQuality,
    SuggestionEventType,
    SuggestionOutcome,
    SuggestionStatus,
)
from app.data.session_calendar import nth_nse_session_after
from app.engines.suggestion_state_engine import Tick
from app.models.trade_suggestion import ImmutableFieldError, TradeSuggestion
from app.models.trade_suggestion_event import AppendOnlyViolation, TradeSuggestionEvent
from app.schemas.suggestion import LevelInput, SuggestionCreateRequest
from app.services import suggestion_service as svc

GEN = dt.datetime(2026, 9, 28, 4, 30, tzinfo=dt.UTC)  # Monday 10:00 IST
V = LevelQuality.VERIFIED_STRUCTURE.value
A = LevelQuality.ATR_DERIVED.value


def request(**overrides) -> SuggestionCreateRequest:
    levels = {
        "entry_low": LevelInput(price=100.0, quality=V, provenance="20D swing-low support"),
        "entry_high": LevelInput(price=102.0, quality=A, provenance="support + 0.75*ATR14"),
        "target_1": LevelInput(price=110.0, quality=V, provenance="20D high"),
        "target_2": LevelInput(price=120.0, quality=A, provenance="20D high + 2*ATR14"),
        "stop_loss": LevelInput(price=95.0, quality=A, provenance="support - 0.25*ATR14"),
    }
    levels.update(overrides.pop("levels", {}))
    base = dict(
        scanner_type="MTF", market="NSE_EQ", symbol="NSE:TEST-EQ", instrument_type="EQUITY",
        direction="LONG", setup_type="PULLBACK", scanner_run_id=42, generated_at=GEN,
        generation_market_price=101.0, generation_price_source="QUOTE",
        market_status="MARKET_OPEN_LIVE", data_quality="HIGH", levels=levels,
        evidence_snapshot={"rsi_14": 55.2, "volume_ratio": 1.4},
    )
    base.update(overrides)
    return SuggestionCreateRequest(**base)


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar()


# ---- creation -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creation_waits_for_entry_and_stores_generation_price(db_session):
    result = await svc.create_suggestion(db_session, request())
    assert result.status == CreationStatus.CREATED

    row = await db_session.get(TradeSuggestion, result.suggestion_id)
    assert row.status == SuggestionStatus.WAITING_ENTRY and row.outcome == SuggestionOutcome.PENDING
    assert row.entry_triggered_at is None and row.entry_triggered_price is None
    assert float(row.generation_market_price) == 101.0
    assert row.generation_price_zone_position == "INSIDE"  # in zone, but NOT an entry
    assert row.entry_rule == "FRESH_TOUCH_AFTER_CREATION"
    assert row.entry_window_sessions == 5 and row.max_holding_sessions == 20
    # 5 NSE sessions after Mon 2026-09-28: Sep 29, Sep 30, Oct 1, (Oct 2 holiday), Oct 5, Oct 6.
    assert row.entry_deadline_session_date == dt.date(2026, 10, 6)
    assert row.session_calendar_verified is True
    assert row.evidence_snapshot == {"rsi_14": 55.2, "volume_ratio": 1.4}

    events = await svc.list_events(db_session, row.id)
    assert [e.event_type for e in events] == [SuggestionEventType.SUGGESTION_CREATED]
    assert events[0].sequence == 1


@pytest.mark.asyncio
async def test_fresh_touch_through_service_sets_holding_deadline(db_session):
    result = await svc.create_suggestion(db_session, request())
    events = await svc.apply_observations(
        db_session, result.suggestion_id,
        [Tick(at=GEN, price=101.0), Tick(at=GEN + dt.timedelta(days=1), price=101.5)],
    )
    assert [e.event_type for e in events] == [SuggestionEventType.ENTRY_TRIGGERED]
    row = await db_session.get(TradeSuggestion, result.suggestion_id)
    assert row.status == SuggestionStatus.ACTIVE
    assert float(row.entry_triggered_price) == 101.5
    assert float(row.generation_market_price) == 101.0  # kept separately for the immediate-vs-fresh study
    expected, _ = nth_nse_session_after(dt.date(2026, 9, 29), 20)
    assert row.holding_deadline_session_date == expected


@pytest.mark.asyncio
async def test_full_lifecycle_events_are_sequenced(db_session):
    result = await svc.create_suggestion(db_session, request())
    sid = result.suggestion_id
    await svc.apply_observations(db_session, sid, [
        Tick(GEN + dt.timedelta(minutes=1), 101.0),
        Tick(GEN + dt.timedelta(minutes=2), 111.0),
        Tick(GEN + dt.timedelta(minutes=3), 94.0),
    ])
    row = await db_session.get(TradeSuggestion, sid)
    assert row.outcome == SuggestionOutcome.PARTIAL_SUCCESS
    assert row.open_dedup_key is None  # terminal -> key released
    events = await svc.list_events(db_session, sid)
    assert [e.sequence for e in events] == [1, 2, 3, 4, 5]
    stop = events[-1]
    assert stop.event_type == SuggestionEventType.STOP_HIT
    assert float(stop.threshold_price) == 95.0 and float(stop.observed_market_price) == 94.0


# ---- level quality ----------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("level,quality", [
    ("target_1", LevelQuality.FALLBACK.value),
    ("stop_loss", LevelQuality.FALLBACK.value),
    ("entry_low", LevelQuality.UNAVAILABLE.value),
    ("stop_loss", LevelQuality.UNAVAILABLE.value),
])
async def test_fallback_or_unavailable_required_level_is_rejected(db_session, level, quality):
    result = await svc.create_suggestion(db_session, request(levels={level: LevelInput(price=96.0, quality=quality)}))
    assert result.status == CreationStatus.REJECTED_LEVELS
    assert any(level in r for r in result.reasons)
    assert await _count(db_session, TradeSuggestion) == 0  # nothing tracked


@pytest.mark.asyncio
async def test_missing_required_level_is_rejected(db_session):
    result = await svc.create_suggestion(db_session, request(levels={"target_1": LevelInput(price=None, quality=V)}))
    assert result.status == CreationStatus.REJECTED_LEVELS
    assert "target_1 is unavailable" in result.reasons


@pytest.mark.asyncio
async def test_fallback_target2_is_excluded_with_a_recorded_note(db_session):
    result = await svc.create_suggestion(
        db_session, request(levels={"target_2": LevelInput(price=125.0, quality=LevelQuality.FALLBACK.value)})
    )
    assert result.status == CreationStatus.CREATED
    row = await db_session.get(TradeSuggestion, result.suggestion_id)
    assert row.target_2 is None
    assert any("target_2 excluded" in n for n in row.level_notes)
    assert row.level_quality["target_2"]["quality"] == LevelQuality.FALLBACK.value


@pytest.mark.asyncio
async def test_incoherent_geometry_is_rejected(db_session):
    result = await svc.create_suggestion(db_session, request(levels={"stop_loss": LevelInput(price=103.0, quality=V)}))
    assert result.status == CreationStatus.REJECTED_LEVELS


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("data_quality", "STALE"), ("data_quality", "UNAVAILABLE"), ("market_status", "STALE"),
    ("generation_market_price", None),
])
async def test_stale_or_unavailable_critical_data_is_rejected(db_session, field, value):
    result = await svc.create_suggestion(db_session, request(**{field: value}))
    assert result.status == CreationStatus.REJECTED_DATA_QUALITY
    assert await _count(db_session, TradeSuggestion) == 0


@pytest.mark.asyncio
async def test_scanner_without_approved_lifecycle_rules_is_rejected(db_session):
    result = await svc.create_suggestion(db_session, request(scanner_type="INTRADAY"))
    assert result.status == CreationStatus.REJECTED_NO_LIFECYCLE_RULES


# ---- duplicate prevention ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeat_signal_is_logged_against_the_open_suggestion(db_session):
    first = await svc.create_suggestion(db_session, request())
    second = await svc.create_suggestion(
        db_session, request(generated_at=GEN + dt.timedelta(hours=1), generation_market_price=103.0,
                            scanner_run_id=43, evidence_snapshot={"rsi_14": 60.0}),
    )
    assert second.status == CreationStatus.DUPLICATE_OPEN and second.suggestion_id == first.suggestion_id
    assert await _count(db_session, TradeSuggestion) == 1

    row = await db_session.get(TradeSuggestion, first.suggestion_id)
    assert row.evidence_snapshot == {"rsi_14": 55.2, "volume_ratio": 1.4}  # original snapshot untouched
    events = await svc.list_events(db_session, row.id)
    assert [e.event_type for e in events] == [SuggestionEventType.SUGGESTION_CREATED, SuggestionEventType.SIGNAL_REPEATED]
    assert events[1].detail["scanner_run_id"] == 43


@pytest.mark.asyncio
async def test_other_direction_or_explicit_group_can_coexist(db_session):
    await svc.create_suggestion(db_session, request())
    short = await svc.create_suggestion(db_session, request(
        direction="SHORT",
        levels={"entry_low": LevelInput(price=98.0, quality=V), "entry_high": LevelInput(price=100.0, quality=V),
                "target_1": LevelInput(price=90.0, quality=V), "target_2": LevelInput(price=80.0, quality=V),
                "stop_loss": LevelInput(price=105.0, quality=V)},
    ))
    assert short.status == CreationStatus.CREATED
    other_group = await svc.create_suggestion(db_session, request(coexistence_group="BREAKOUT_VARIANT"))
    assert other_group.status == CreationStatus.CREATED
    assert await _count(db_session, TradeSuggestion) == 3


@pytest.mark.asyncio
async def test_new_suggestion_allowed_after_previous_one_closed(db_session):
    first = await svc.create_suggestion(db_session, request())
    await svc.cancel_suggestion(db_session, first.suggestion_id, "test close")
    again = await svc.create_suggestion(db_session, request(generated_at=GEN + dt.timedelta(days=1)))
    assert again.status == CreationStatus.CREATED and again.suggestion_id != first.suggestion_id


@pytest.mark.asyncio
async def test_database_rejects_two_open_rows_with_the_same_key(db_session):
    from sqlalchemy.exc import IntegrityError

    await svc.create_suggestion(db_session, request())
    row = await db_session.get(TradeSuggestion, 1)
    clone = TradeSuggestion(**{c.name: getattr(row, c.name) for c in TradeSuggestion.__table__.columns if c.name != "id"})
    db_session.add(clone)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ---- immutability / append-only ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_log_is_append_only(db_session):
    result = await svc.create_suggestion(db_session, request())
    event = (await svc.list_events(db_session, result.suggestion_id))[0]

    event.detail = {"tampered": True}
    with pytest.raises(AppendOnlyViolation):
        await db_session.flush()
    await db_session.rollback()

    event = (await svc.list_events(db_session, result.suggestion_id))[0]
    await db_session.delete(event)
    with pytest.raises(AppendOnlyViolation):
        await db_session.flush()
    await db_session.rollback()
    assert await _count(db_session, TradeSuggestionEvent) == 1


@pytest.mark.asyncio
async def test_generation_snapshot_and_levels_are_immutable(db_session):
    result = await svc.create_suggestion(db_session, request())
    row = await db_session.get(TradeSuggestion, result.suggestion_id)
    row.evidence_snapshot = {"rsi_14": 99.0}
    with pytest.raises(ImmutableFieldError):
        await db_session.flush()
    await db_session.rollback()

    row = await db_session.get(TradeSuggestion, result.suggestion_id)
    row.stop_loss = 90.0
    with pytest.raises(ImmutableFieldError):
        await db_session.flush()
    await db_session.rollback()


# ---- history / calendar ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_window_filters_but_never_deletes(db_session):
    old = await svc.create_suggestion(db_session, request(symbol="NSE:OLD-EQ", generated_at=GEN - dt.timedelta(days=30)))
    new = await svc.create_suggestion(db_session, request(symbol="NSE:NEW-EQ"))
    recent = await svc.list_suggestions(db_session, since=GEN - dt.timedelta(days=7))
    assert [r.id for r in recent] == [new.suggestion_id]
    assert await _count(db_session, TradeSuggestion) == 2
    assert await db_session.get(TradeSuggestion, old.suggestion_id) is not None


@pytest.mark.asyncio
async def test_deadline_beyond_verified_holiday_calendar_is_flagged(db_session):
    late = dt.datetime(2026, 12, 28, 4, 30, tzinfo=dt.UTC)
    result = await svc.create_suggestion(db_session, request(generated_at=late))
    row = await db_session.get(TradeSuggestion, result.suggestion_id)
    assert row.entry_deadline_session_date.year == 2027
    assert row.session_calendar_verified is False
