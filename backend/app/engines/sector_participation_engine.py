"""Sector Participation analysis (Phase 6 Objective 4) -- an ANALYTICAL
classification, separate from and never fed back into `sector_context`'s
score. Exists specifically to surface cases like RELIANCE in Phase 5:
STRONG sector label, but the stock itself materially underperforming that
sector and in a downtrend -- which the current sector_context scoring
doesn't distinguish from genuine participation.

Threshold (+/-2.0%) reuses the SAME breakpoint relative_strength_engine.py
already uses for stock-vs-NIFTY/sector classification -- one documented
convention, not a new arbitrary number invented for this module.
"""

from app.schemas.common import EvidenceItem

PARTICIPATION_THRESHOLD_PCT = 2.0

LEADING_SECTOR = "LEADING_SECTOR"
PARTICIPATING = "PARTICIPATING"
LAGGING_SECTOR = "LAGGING_SECTOR"
DIVERGING = "DIVERGING"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

_DOWNTRENDS = ("STRONG_DOWNTREND", "DOWNTREND")
_UPTRENDS = ("STRONG_UPTREND", "UPTREND")


def classify_sector_participation(
    stock_return_20d: float | None,
    sector_return_20d: float | None,
    trend_structure: str | None,
    stock_return_5d: float | None = None,
    sector_return_5d: float | None = None,
) -> tuple[str, list[EvidenceItem]]:
    """Returns (state, evidence). Never fabricates a state from partial data
    -- both 20D returns are required (the classification-driving window,
    matching relative_strength_engine.py's own primary window); 5D returns
    are optional supplementary evidence only, never a second vote."""
    if stock_return_20d is None or sector_return_20d is None:
        return INSUFFICIENT_DATA, []

    vs_sector = round(stock_return_20d - sector_return_20d, 3)
    evidence = [
        EvidenceItem(
            label="Stock vs sector (20D)", detail=f"Stock {stock_return_20d:+.2f}% vs sector {sector_return_20d:+.2f}% over 20D",
            value=vs_sector, is_positive=vs_sector > 0,
        )
    ]
    if stock_return_5d is not None and sector_return_5d is not None:
        vs_sector_5d = round(stock_return_5d - sector_return_5d, 3)
        evidence.append(
            EvidenceItem(
                label="Stock vs sector (5D)", detail=f"Stock {stock_return_5d:+.2f}% vs sector {sector_return_5d:+.2f}% over 5D",
                value=vs_sector_5d, is_positive=vs_sector_5d > 0,
            )
        )

    return _classify_from_delta(vs_sector, trend_structure), evidence


def _classify_from_delta(vs_sector: float, trend_structure: str | None) -> str:
    if vs_sector >= PARTICIPATION_THRESHOLD_PCT and trend_structure in _UPTRENDS:
        return LEADING_SECTOR
    if vs_sector <= -PARTICIPATION_THRESHOLD_PCT and trend_structure in _DOWNTRENDS:
        return DIVERGING
    if vs_sector <= -PARTICIPATION_THRESHOLD_PCT:
        return LAGGING_SECTOR
    return PARTICIPATING


def classify_sector_participation_from_deltas(
    vs_sector_pct_20d: float | None,
    trend_structure: str | None,
) -> tuple[str, list[EvidenceItem]]:
    """Delta-only variant for callers that only have the already-computed
    stock-vs-sector difference (e.g. CandidateResponse.relative_strength.
    vs_sector_pct_20d), not the two raw absolute returns -- used by the
    ad-hoc single-symbol /research-confirmation endpoint, which has no
    reason to re-fetch stock/sector candles just for this. The richer
    raw-returns variant above (with 5D evidence too) is used at observation-
    collection time, where those candles are fetched anyway."""
    if vs_sector_pct_20d is None:
        return INSUFFICIENT_DATA, []

    evidence = [
        EvidenceItem(
            label="Stock vs sector (20D)", detail=f"Stock is {vs_sector_pct_20d:+.2f}% vs its sector over 20D",
            value=vs_sector_pct_20d, is_positive=vs_sector_pct_20d > 0,
        )
    ]
    return _classify_from_delta(vs_sector_pct_20d, trend_structure), evidence
