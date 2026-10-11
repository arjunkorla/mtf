"""Schemas for the shared suggestion tracker (Phase A). Research
recommendations only -- nothing here represents a broker order or account P&L."""

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.core.suggestion_constants import DEFAULT_COEXISTENCE_GROUP, CreationStatus


class LevelInput(BaseModel):
    price: float | None
    quality: str  # LevelQuality
    provenance: str | None = None


class SuggestionCreateRequest(BaseModel):
    scanner_type: str
    market: str
    symbol: str  # the instrument actually tracked (the option contract itself for options)
    underlying_symbol: str | None = None
    instrument_type: str
    direction: str
    setup_type: str
    coexistence_group: str = DEFAULT_COEXISTENCE_GROUP
    scanner_run_id: int | None = None

    generated_at: dt.datetime
    generation_market_price: float | None
    generation_price_source: str
    market_status: str
    data_quality: str

    levels: dict[str, LevelInput]  # entry_low, entry_high, target_1, target_2, stop_loss, invalidation_price
    reference_entry_price: float | None = None
    suggested_holding_period: str | None = None
    score: float | None = None
    confidence: float | None = None

    option_symbol: str | None = None
    option_strike: float | None = None
    option_type: str | None = None
    option_expiry: dt.date | None = None
    expires_at: dt.datetime | None = None

    evidence_snapshot: dict = Field(default_factory=dict)
    research_metadata: dict = Field(default_factory=dict)


class CreationResult(BaseModel):
    status: CreationStatus
    suggestion_id: int | None = None
    reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SuggestionEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    event_type: str
    from_status: str | None
    to_status: str | None
    threshold_price: float | None
    observed_market_price: float | None
    observed_price_basis: str | None
    observed_at: dt.datetime | None
    data_source: str | None
    ambiguous_bar: bool
    detail: dict
    recorded_at: dt.datetime


class SuggestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scanner_type: str
    market: str
    symbol: str
    underlying_symbol: str | None
    instrument_type: str
    direction: str
    setup_type: str
    scanner_run_id: int | None

    generated_at: dt.datetime
    generation_market_price: float
    generation_price_zone_position: str
    market_status: str
    data_quality: str
    entry_rule: str

    entry_low: float
    entry_high: float
    target_1: float
    target_2: float | None
    stop_loss: float
    invalidation_price: float | None
    level_quality: dict
    level_notes: list

    suggested_holding_period: str | None
    entry_deadline_session_date: dt.date | None
    holding_deadline_session_date: dt.date | None
    session_calendar_verified: bool
    score: float | None
    confidence: float | None

    option_symbol: str | None
    option_strike: float | None
    option_type: str | None
    option_expiry: dt.date | None

    status: str
    outcome: str
    entry_triggered_at: dt.datetime | None
    entry_triggered_price: float | None
    target_1_hit_at: dt.datetime | None
    target_1_hit_price: float | None
    target_2_hit_at: dt.datetime | None
    target_2_hit_price: float | None
    stop_hit_at: dt.datetime | None
    stop_hit_price: float | None
    closed_at: dt.datetime | None
    close_price: float | None
    max_favorable_excursion: float | None
    max_adverse_excursion: float | None
    realized_or_marked_return_pct: float | None
    return_is_realized: bool
    ambiguous_bar: bool
    failure_reason: str | None
    last_observed_price: float | None
    last_observed_at: dt.datetime | None


# ---- Phase B read API --------------------------------------------------------------------


class SuggestionListItem(SuggestionResponse):
    tracking_status: str
    reconciled_through: dt.datetime | None


class SuggestionListResponse(BaseModel):
    items: list[SuggestionListItem]
    total: int
    limit: int
    offset: int
    window: dict  # {"from", "to", "defaulted_to_last_7_days"}


class SuggestionDetailResponse(SuggestionListItem):
    generation_price_source: str
    reference_entry_price: float | None
    coexistence_group: str
    entry_window_sessions: int | None
    max_holding_sessions: int | None
    expires_at: dt.datetime | None
    max_favorable_price: float | None
    max_adverse_price: float | None
    post_target_1_adverse_price: float | None
    breakeven_revisited_after_target_1_at: dt.datetime | None
    tracking_status_reason: str | None
    last_evaluated_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime
    evidence_snapshot: dict
    research_metadata: dict
    provisional_live: dict | None = None  # Redis live view -- explicitly NOT committed evidence
    disclaimer: str = ""
