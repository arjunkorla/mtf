"""Market / sector engine (section 14): market regime + sector strength.

A strong stock in a weak sector is treated differently from a strong stock in
a strong sector by feeding `sector_strength_label` into the scoring engine's
market/sector component (see scoring_engine.py), not by altering the stock's
own technical/volume numbers.
"""

from app.core.constants import MarketRegime
from app.data.internal_models import Candle
from app.engines.relative_strength_engine import pct_return
from app.engines.technical_engine import compute_technical_metrics
from app.schemas.stock import RelativeStrengthData, SectorData


def compute_market_regime(nifty_candles: list[Candle] | None) -> str:
    if not nifty_candles or len(nifty_candles) < 200:
        return MarketRegime.INSUFFICIENT_DATA.value

    tech = compute_technical_metrics(nifty_candles)
    if tech.trend_structure in ("STRONG_UPTREND", "UPTREND"):
        return MarketRegime.RISK_ON.value
    if tech.trend_structure in ("STRONG_DOWNTREND", "DOWNTREND"):
        return MarketRegime.RISK_OFF.value
    return MarketRegime.NEUTRAL.value


def compute_sector_strength_label(sector_candles: list[Candle] | None, nifty_candles: list[Candle] | None) -> str | None:
    if not sector_candles or not nifty_candles:
        return None
    sector_return = pct_return(sector_candles, 20)
    nifty_return = pct_return(nifty_candles, 20)
    if sector_return is None or nifty_return is None:
        return None
    diff = sector_return - nifty_return
    if diff > 2.0:
        return "STRONG"
    if diff < -2.0:
        return "WEAK"
    return "NEUTRAL"


def build_sector_data(
    sector_name: str | None,
    sector_candles: list[Candle] | None,
    nifty_candles: list[Candle] | None,
    relative_strength: RelativeStrengthData,
) -> SectorData:
    return SectorData(
        sector_name=sector_name,
        sector_strength_label=compute_sector_strength_label(sector_candles, nifty_candles),
        market_regime=compute_market_regime(nifty_candles),
        relative_strength=relative_strength,
    )
