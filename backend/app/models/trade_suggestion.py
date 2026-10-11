"""One persisted scanner recommendation (Phase A shared suggestion tracker).

Never deleted: the History UI will default to the last 7 days, but every row
is kept permanently for outcome research.

Generation != entry. A suggestion is created WAITING_ENTRY; entry is only
recorded from a genuine post-creation market observation (FRESH_TOUCH_AFTER
_CREATION). generation_market_price is stored separately so immediate-entry
vs fresh-touch can be studied later without rewriting history.

Immutable after creation (enforced by an ORM guard below): the evidence
snapshot, the generation fields and the original levels. Tracking only ever
fills in the entry/exit/excursion columns and appends events.

Duplicate prevention: `open_dedup_key` holds
"{scanner}|{symbol}|{direction}|{coexistence_group}" while the suggestion is
open and NULL once terminal. A plain UNIQUE constraint on it therefore
allows at most one open suggestion per key (NULLs never collide, in both
PostgreSQL and SQLite) without dialect-specific partial indexes.
"""

import datetime as dt

from sqlalchemy import JSON, Boolean, Date, DateTime, Integer, Numeric, String, event, inspect
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TradeSuggestion(Base):
    __tablename__ = "trade_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)

    # --- identity ---------------------------------------------------------
    scanner_type: Mapped[str] = mapped_column(String(16), index=True)  # ScannerType
    market: Mapped[str] = mapped_column(String(16))  # e.g. NSE_EQ / NSE_FO / MCX
    symbol: Mapped[str] = mapped_column(String(64), index=True)  # the instrument actually tracked
    underlying_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    instrument_type: Mapped[str] = mapped_column(String(16))  # EQUITY / FUTURE / OPTION / INDEX
    direction: Mapped[str] = mapped_column(String(8))  # Direction
    setup_type: Mapped[str] = mapped_column(String(64))
    coexistence_group: Mapped[str] = mapped_column(String(32))
    open_dedup_key: Mapped[str | None] = mapped_column(String(256), unique=True, nullable=True)

    scanner_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # per-scanner run table, no FK

    # --- generation (immutable) ------------------------------------------
    generated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    generation_session_date: Mapped[dt.date] = mapped_column(Date, index=True)
    generation_market_price: Mapped[float] = mapped_column(Numeric(18, 4))
    generation_price_source: Mapped[str] = mapped_column(String(32))
    generation_price_zone_position: Mapped[str] = mapped_column(String(16))  # INSIDE / ABOVE / BELOW
    market_status: Mapped[str] = mapped_column(String(32))
    data_quality: Mapped[str] = mapped_column(String(32))
    entry_rule: Mapped[str] = mapped_column(String(48))

    # --- original levels (immutable) --------------------------------------
    entry_low: Mapped[float] = mapped_column(Numeric(18, 4))
    entry_high: Mapped[float] = mapped_column(Numeric(18, 4))
    reference_entry_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    target_1: Mapped[float] = mapped_column(Numeric(18, 4))
    target_2: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    stop_loss: Mapped[float] = mapped_column(Numeric(18, 4))
    invalidation_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    level_quality: Mapped[dict] = mapped_column(JSON, default=dict)  # per-level LevelQuality + provenance
    level_notes: Mapped[list] = mapped_column(JSON, default=list)  # e.g. why target_2 was excluded

    # --- lifecycle rules snapshot (immutable) -------------------------------
    suggested_holding_period: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entry_window_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_holding_sessions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_deadline_session_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    holding_deadline_session_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)  # set at entry
    session_calendar_verified: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    score: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(8, 3), nullable=True)

    # --- options (nullable) ------------------------------------------------
    option_symbol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    option_strike: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String(4), nullable=True)
    option_expiry: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    # --- lifecycle -----------------------------------------------------------
    status: Mapped[str] = mapped_column(String(32), index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)

    entry_triggered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_triggered_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    target_1_hit_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_1_hit_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    target_2_hit_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    target_2_hit_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    stop_hit_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stop_hit_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    max_favorable_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    max_adverse_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    max_favorable_excursion: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)  # % vs entry
    max_adverse_excursion: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)  # % vs entry (<= 0)
    realized_or_marked_return_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    return_is_realized: Mapped[bool] = mapped_column(Boolean, default=False)

    # Breakeven-after-T1 study data (the methodology itself is NOT applied):
    post_target_1_adverse_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    breakeven_revisited_after_target_1_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ambiguous_bar: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    last_observed_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    last_observed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_evaluated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- tracker bookkeeping (Phase B, migration 0004) ------------------------
    # reconciled_through: every candle with start < this instant has been
    # applied (the tracker's idempotency watermark -- persisted atomically with
    # the state/events it produced). NULL -> nothing reconciled yet.
    reconciled_through: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tracking_status: Mapped[str] = mapped_column(String(32), default="NOT_TRACKED")  # TrackingStatus
    tracking_status_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # --- tracker-owned excursion timing (Phase D, migration 0005) --------------
    # When the favorable/adverse extreme was FIRST observed (bar end or tick
    # time -- bar resolution), and the adverse extreme through the bar BEFORE
    # the target-1 bar (a lower bound: the target-1 bar's own low may precede
    # the touch). NULL where not observed -- never back-filled.
    max_favorable_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_adverse_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_adverse_price_before_target_1: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    # --- evidence (immutable) -------------------------------------------------
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # features AT generation time
    research_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC))
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.UTC), onupdate=lambda: dt.datetime.now(dt.UTC)
    )

    events: Mapped[list["TradeSuggestionEvent"]] = relationship(  # noqa: F821
        back_populates="suggestion", order_by="TradeSuggestionEvent.sequence"
    )


IMMUTABLE_SUGGESTION_FIELDS = (
    "scanner_type", "market", "symbol", "underlying_symbol", "instrument_type", "direction", "setup_type",
    "coexistence_group", "scanner_run_id",
    "generated_at", "generation_session_date", "generation_market_price", "generation_price_source",
    "generation_price_zone_position", "market_status", "data_quality", "entry_rule",
    "entry_low", "entry_high", "reference_entry_price", "target_1", "target_2", "stop_loss", "invalidation_price",
    "level_quality", "level_notes",
    "entry_window_sessions", "max_holding_sessions", "entry_deadline_session_date",
    "option_symbol", "option_strike", "option_type", "option_expiry",
    "score", "confidence", "evidence_snapshot", "research_metadata",
)


class ImmutableFieldError(RuntimeError):
    pass


@event.listens_for(TradeSuggestion, "before_update")
def _guard_immutable_fields(mapper, connection, target: TradeSuggestion) -> None:
    state = inspect(target)
    changed = [name for name in IMMUTABLE_SUGGESTION_FIELDS if state.attrs[name].history.has_changes()]
    if changed:
        raise ImmutableFieldError(
            f"TradeSuggestion {target.id}: generation-time fields are immutable, refused to change {changed}"
        )
