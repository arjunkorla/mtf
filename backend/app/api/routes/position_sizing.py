"""POST /api/position-size"""

from fastapi import APIRouter, HTTPException

from app.engines.risk_engine import InvalidRiskInputError, compute_position_size
from app.schemas.position_sizing import PositionSizeRequest, PositionSizeResponse

router = APIRouter()


@router.post("/position-size", response_model=PositionSizeResponse)
async def position_size(request: PositionSizeRequest) -> PositionSizeResponse:
    try:
        sizing = compute_position_size(
            available_capital=request.available_capital,
            risk_percent=request.risk_percent,
            entry_price=request.entry_price,
            invalidation_price=request.invalidation_price,
            max_position_pct_of_capital=request.max_position_pct_of_capital,
        )
    except InvalidRiskInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return PositionSizeResponse(position_sizing=sizing)
