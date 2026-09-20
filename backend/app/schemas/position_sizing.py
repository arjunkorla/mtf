"""POST /api/position-size request/response (section 18/21)."""

from pydantic import BaseModel, Field

from app.schemas.common import PositionSizing


class PositionSizeRequest(BaseModel):
    available_capital: float = Field(gt=0)
    risk_percent: float = Field(gt=0, le=100)
    entry_price: float = Field(gt=0)
    invalidation_price: float = Field(gt=0)
    max_position_pct_of_capital: float | None = Field(default=None, gt=0, le=100)


class PositionSizeResponse(BaseModel):
    position_sizing: PositionSizing
