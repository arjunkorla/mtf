"""Relative strength engine (section 10): stock vs NIFTY and vs sector."""

from app.core.constants import RelativeStrengthLabel
from app.data.internal_models import Candle
from app.schemas.stock import RelativeStrengthData


def pct_return(candles: list[Candle], lookback_days: int) -> float | None:
    if len(candles) <= lookback_days:
        return None
    start = candles[-(lookback_days + 1)].close
    end = candles[-1].close
    if start <= 0:
        return None
    return (end - start) / start * 100


def compute_relative_strength(
    stock_candles: list[Candle],
    nifty_candles: list[Candle] | None,
    sector_candles: list[Candle] | None,
    lookback_days: int = 20,
) -> RelativeStrengthData:
    stock_return = pct_return(stock_candles, lookback_days)

    vs_nifty: float | None = None
    if stock_return is not None and nifty_candles:
        nifty_return = pct_return(nifty_candles, lookback_days)
        if nifty_return is not None:
            vs_nifty = round(stock_return - nifty_return, 3)

    vs_sector: float | None = None
    if stock_return is not None and sector_candles:
        sector_return = pct_return(sector_candles, lookback_days)
        if sector_return is not None:
            vs_sector = round(stock_return - sector_return, 3)

    if vs_nifty is None and vs_sector is None:
        label = RelativeStrengthLabel.INSUFFICIENT_DATA
    else:
        primary = vs_nifty if vs_nifty is not None else vs_sector
        if primary > 2.0:
            label = RelativeStrengthLabel.OUTPERFORM
        elif primary < -2.0:
            label = RelativeStrengthLabel.UNDERPERFORM
        else:
            label = RelativeStrengthLabel.NEUTRAL

    return RelativeStrengthData(
        label=label.value,
        vs_nifty_pct_20d=vs_nifty,
        vs_sector_pct_20d=vs_sector,
    )
