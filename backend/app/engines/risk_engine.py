"""Risk / position-sizing engine (section 18).

  max_risk = available_capital * risk_percent / 100
  risk_per_share = entry - invalidation
  quantity = floor(max_risk / risk_per_share)

Applies practical rounding and a configurable max-position-of-capital cap.
Never recommends spending more than available_capital.
"""

import math

from app.core.exceptions import MtfError
from app.schemas.common import PositionSizing


class InvalidRiskInputError(MtfError):
    pass


def compute_position_size(
    available_capital: float,
    risk_percent: float,
    entry_price: float,
    invalidation_price: float,
    max_position_pct_of_capital: float | None = None,
    resistance_scenario_1: float | None = None,
    resistance_scenario_2: float | None = None,
) -> PositionSizing:
    if available_capital <= 0:
        raise InvalidRiskInputError("available_capital must be positive")
    if not (0 < risk_percent <= 100):
        raise InvalidRiskInputError("risk_percent must be in (0, 100]")
    if entry_price <= 0:
        raise InvalidRiskInputError("entry_price must be positive")
    if invalidation_price <= 0:
        raise InvalidRiskInputError("invalidation_price must be positive")
    if invalidation_price >= entry_price:
        raise InvalidRiskInputError("invalidation_price must be below entry_price for a long MTF setup")

    max_risk = available_capital * (risk_percent / 100)
    risk_per_share = entry_price - invalidation_price
    raw_quantity = max_risk / risk_per_share
    quantity = math.floor(raw_quantity)

    notes: list[str] = []

    max_affordable_qty = math.floor(available_capital / entry_price)
    if quantity > max_affordable_qty:
        quantity = max_affordable_qty
        notes.append("Quantity capped by available capital, not just risk budget.")

    if max_position_pct_of_capital is not None:
        cap_capital = available_capital * (max_position_pct_of_capital / 100)
        cap_qty = math.floor(cap_capital / entry_price)
        if quantity > cap_qty:
            quantity = cap_qty
            notes.append(f"Quantity capped at {max_position_pct_of_capital:.0f}% of available capital.")

    quantity = max(quantity, 0)
    if quantity == 0:
        notes.append("Computed quantity is 0 -- risk budget or capital is too small for this entry/invalidation gap.")

    capital_required = round(quantity * entry_price, 2)
    actual_rupee_risk = round(quantity * risk_per_share, 2)
    capital_utilization_pct = round((capital_required / available_capital) * 100, 2) if available_capital else 0.0

    rr1 = None
    rr2 = None
    if resistance_scenario_1 is not None and risk_per_share > 0:
        rr1 = round((resistance_scenario_1 - entry_price) / risk_per_share, 2)
    if resistance_scenario_2 is not None and risk_per_share > 0:
        rr2 = round((resistance_scenario_2 - entry_price) / risk_per_share, 2)

    return PositionSizing(
        available_capital=available_capital,
        risk_percent=risk_percent,
        entry_price=entry_price,
        invalidation_price=invalidation_price,
        risk_per_share=round(risk_per_share, 2),
        max_rupee_risk=round(max_risk, 2),
        quantity=quantity,
        capital_required=capital_required,
        capital_utilization_pct=capital_utilization_pct,
        reward_to_risk_scenario_1=rr1,
        reward_to_risk_scenario_2=rr2,
        notes=notes,
    )
