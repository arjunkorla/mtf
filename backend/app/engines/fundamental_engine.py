"""Fundamental engine (section 12). Passes through validated fundamentals
data only -- never fabricates a metric, and missing fundamentals are marked
unavailable rather than treated as a positive signal.
"""

from app.models.fundamentals import Fundamentals
from app.schemas.stock import FundamentalData


def build_fundamental_data(fundamentals: Fundamentals | None) -> FundamentalData:
    if fundamentals is None or not fundamentals.is_available:
        return FundamentalData(is_available=False)

    return FundamentalData(
        is_available=True,
        revenue_growth_yoy_pct=fundamentals.revenue_growth_yoy_pct,
        profit_growth_yoy_pct=fundamentals.profit_growth_yoy_pct,
        eps=fundamentals.eps,
        net_margin_pct=fundamentals.net_margin_pct,
        debt_to_equity=fundamentals.debt_to_equity,
        roe_pct=fundamentals.roe_pct,
        roce_pct=fundamentals.roce_pct,
        pe_ratio=fundamentals.pe_ratio,
    )
