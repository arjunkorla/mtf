"""Forward outcome measurement (Phase 6 Objective 6).

Computes returns/excursions ONLY from real historical candles that
genuinely occurred after an observation's session_date. Never estimates,
interpolates, or backdates a horizon that hasn't actually elapsed yet --
"has N trading days elapsed" is answered by counting REAL candles returned
by the data source, not by adding N calendar days (which would be wrong
across weekends/holidays).

An observation's outcome starts and stays OUTCOME_PENDING until at least
one future candle exists; OUTCOME_PARTIAL once some (not all) of the five
horizons are computable; OUTCOME_COMPUTED once all five are. This is an
explicit extension beyond the bare PENDING/COMPUTED the brief describes --
justified because refusing to record the 1D/3D outcome just because the 20D
one isn't due yet would throw away real, available evidence.
"""

from dataclasses import dataclass

from app.data.internal_models import Candle

HORIZONS = (1, 3, 5, 10, 20)

OUTCOME_PENDING = "OUTCOME_PENDING"
OUTCOME_PARTIAL = "OUTCOME_PARTIAL"
OUTCOME_COMPUTED = "OUTCOME_COMPUTED"


@dataclass(frozen=True, slots=True)
class OutcomeResult:
    status: str
    next_1d_return: float | None = None
    next_3d_return: float | None = None
    next_5d_return: float | None = None
    next_10d_return: float | None = None
    next_20d_return: float | None = None
    maximum_favorable_excursion: float | None = None
    maximum_adverse_excursion: float | None = None
    invalidation_hit: bool | None = None
    entry_zone_reached: bool | None = None


def compute_outcome(
    observed_price: float | None,
    invalidation: float | None,
    entry_zone_low: float | None,
    entry_zone_high: float | None,
    future_candles: list[Candle],
) -> OutcomeResult:
    """`future_candles` must be real daily candles strictly after the
    observation's session_date, sorted ascending by trade_date -- the
    caller (outcome_service.py) is responsible for fetching only genuine
    elapsed history, never synthesizing it."""
    if observed_price is None or not future_candles:
        return OutcomeResult(status=OUTCOME_PENDING)

    returns: dict[int, float | None] = {}
    for horizon in HORIZONS:
        if len(future_candles) >= horizon:
            close_at_horizon = future_candles[horizon - 1].close
            returns[horizon] = round((close_at_horizon - observed_price) / observed_price * 100, 3)
        else:
            returns[horizon] = None

    highs = [c.high for c in future_candles]
    lows = [c.low for c in future_candles]
    mfe = round((max(highs) - observed_price) / observed_price * 100, 3)
    mae = round((min(lows) - observed_price) / observed_price * 100, 3)

    invalidation_hit = any(c.low <= invalidation for c in future_candles) if invalidation is not None else None
    entry_zone_reached = (
        any(c.low <= entry_zone_high and c.high >= entry_zone_low for c in future_candles)
        if entry_zone_low is not None and entry_zone_high is not None
        else None
    )

    computed_count = sum(1 for v in returns.values() if v is not None)
    status = OUTCOME_COMPUTED if computed_count == len(HORIZONS) else OUTCOME_PARTIAL

    return OutcomeResult(
        status=status,
        next_1d_return=returns[1], next_3d_return=returns[3], next_5d_return=returns[5],
        next_10d_return=returns[10], next_20d_return=returns[20],
        maximum_favorable_excursion=mfe, maximum_adverse_excursion=mae,
        invalidation_hit=invalidation_hit, entry_zone_reached=entry_zone_reached,
    )
