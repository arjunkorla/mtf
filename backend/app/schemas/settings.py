"""GET/PUT /api/settings -- configurable scanner thresholds (section 16).

Never includes secrets (FYERS keys, DB/Redis URLs, AI keys) -- those stay
server-side env vars only, per section 29.
"""

from pydantic import BaseModel, Field


class ScannerSettings(BaseModel):
    min_price: float = Field(default=20.0, gt=0)
    min_avg_daily_turnover: float = Field(default=5_00_00_000, gt=0)
    min_avg_daily_volume: float = Field(default=100_000, gt=0)
    min_history_days: int = Field(default=100, ge=1)
    max_candidates: int = Field(default=10, ge=1, le=50)
    min_candidates: int = Field(default=3, ge=1)
    mtf_eligible_only: bool = True
    fno_only: bool = False
    exclude_penny_stocks: bool = True

    default_holding_period: str = "1-4 weeks"
    default_risk_percent: float = Field(default=2.0, gt=0, le=100)

    ai_provider: str = "none"
