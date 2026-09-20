"""Request/response models for the scanner endpoints (section 21) and the
detailed stock analysis endpoint. This is the primary frontend contract --
keep field names stable.
"""

import datetime as dt

from pydantic import BaseModel, Field, field_validator

from app.data.universe import get_seed_universe
from app.schemas.common import (
    DataQuality,
    EvidenceItem,
    InstitutionalFootprint,
    PositionSizing,
    ScenarioLevels,
    ScoreComponent,
    SetupDetection,
)
from app.schemas.stock import (
    FnoData,
    FundamentalData,
    MarketData,
    NewsData,
    RelativeStrengthData,
    SectorData,
    TechnicalData,
    VolumeData,
)


class ScannerRunRequest(BaseModel):
    available_capital: float = Field(gt=0)
    risk_percent: float = Field(gt=0, le=100)
    max_positions: int = Field(default=5, ge=1, le=10)
    holding_period: str = Field(default="1-4 weeks")
    symbols: list[str] | None = Field(
        default=None,
        description=(
            "Optional subset of the configured universe to analyze, e.g. "
            '["NSE:RELIANCE-EQ", "NSE:INFY-EQ"]. Omit (or pass null) to scan '
            "the full configured universe -- this is purely additive and "
            "does not change default behavior."
        ),
    )

    @field_validator("symbols")
    @classmethod
    def _validate_symbols(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(value) == 0:
            raise ValueError(
                "symbols cannot be an empty list -- omit the field entirely to scan the full universe"
            )

        # De-duplicate while preserving first-seen order.
        deduped = list(dict.fromkeys(value))

        valid_symbols = {entry.symbol for entry in get_seed_universe()}
        unknown = [s for s in deduped if s not in valid_symbols]
        if unknown:
            raise ValueError(f"unknown symbol(s) not in the configured universe: {', '.join(unknown)}")

        return deduped


class CandidateResponse(BaseModel):
    """One ranked MTF candidate -- section 21/31 output shape."""

    symbol: str
    company_name: str
    sector: str | None = None

    score: float
    score_components: list[ScoreComponent]
    signal_quality: str

    price: float
    entry_zone_low: float
    entry_zone_high: float
    invalidation: float
    scenarios: ScenarioLevels

    setup: SetupDetection
    institutional_footprint: InstitutionalFootprint

    technical: TechnicalData
    volume: VolumeData
    fno: FnoData
    fundamentals: FundamentalData
    relative_strength: RelativeStrengthData
    sector_context: SectorData
    news: NewsData

    position_sizing: PositionSizing

    evidence: list[EvidenceItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    data_quality: DataQuality

    ai_research: dict | None = None  # populated lazily via /stocks/{symbol}/analysis


class ScannerRunResponse(BaseModel):
    run_id: int
    status: str
    generated_at: dt.datetime
    holding_period: str
    stocks_analyzed: int
    stocks_rejected: int
    stocks_selected: int
    rejection_summary: dict[str, int] = Field(default_factory=dict)
    candidates: list[CandidateResponse]


class ScannerResultsResponse(BaseModel):
    run_id: int
    status: str
    generated_at: dt.datetime
    candidates: list[CandidateResponse]


class StockAnalysisResponse(BaseModel):
    """GET /api/stocks/{symbol}/analysis -- full candidate view plus AI narrative."""

    symbol: str
    company_name: str
    market_data: MarketData
    candidate: CandidateResponse
    ai_research: dict | None = None
