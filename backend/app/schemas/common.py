"""Shared building-block response models."""

import datetime as dt

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """One measurable, sourced observation -- never a subjective claim."""

    label: str
    detail: str
    value: float | str | None = None
    is_positive: bool | None = None  # None = neutral/informational


class ScoreComponent(BaseModel):
    """One weighted component of the MTF score (section 15)."""

    name: str
    weight: float
    points_awarded: float | None = None  # None if unavailable
    available: bool
    reason_unavailable: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)


class DataQuality(BaseModel):
    """Section 25 -- every scanner result must carry this."""

    data_quality_score: float
    missing_data: list[str] = Field(default_factory=list)
    stale_data: list[str] = Field(default_factory=list)
    source_timestamps: dict[str, dt.datetime] = Field(default_factory=dict)


class ScenarioLevels(BaseModel):
    """Section 19 -- descriptive scenarios, never guaranteed targets."""

    entry_zone_low: float
    entry_zone_high: float
    preferred_entry: float
    invalidation: float
    resistance_scenario_1: float
    resistance_scenario_1_label: str = "Potential objective"
    resistance_scenario_2: float | None = None
    resistance_scenario_2_label: str = "Potential objective"


class PositionSizing(BaseModel):
    """Section 18 output, embedded in candidate responses."""

    available_capital: float
    risk_percent: float
    entry_price: float
    invalidation_price: float
    risk_per_share: float
    max_rupee_risk: float
    quantity: int
    capital_required: float
    capital_utilization_pct: float
    reward_to_risk_scenario_1: float | None = None
    reward_to_risk_scenario_2: float | None = None
    notes: list[str] = Field(default_factory=list)


class InstitutionalFootprint(BaseModel):
    """Section 9 output. Level is always one of the fixed enum values."""

    institutional_footprint_score: float | None
    institutional_footprint_level: str
    evidence: list[EvidenceItem] = Field(default_factory=list)


class SetupDetection(BaseModel):
    """Section 17 output."""

    setup_type: str
    setup_strength: str | None = None
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)
    conflicting_evidence: list[EvidenceItem] = Field(default_factory=list)
    invalidation_condition: str | None = None
