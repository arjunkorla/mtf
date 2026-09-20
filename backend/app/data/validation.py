"""Sanity-checks normalized market data before it reaches the calculation
engines (section 6/25). Returns problems found rather than raising, so
callers can decide whether to reject the candidate or just flag data quality.
"""

import datetime as dt
from dataclasses import dataclass, field

from app.data.internal_models import Candle


@dataclass
class ValidationResult:
    is_valid: bool
    issues: list[str] = field(default_factory=list)


def validate_candles(candles: list[Candle], min_history_days: int) -> ValidationResult:
    issues: list[str] = []

    if len(candles) < min_history_days:
        issues.append(f"insufficient_history:{len(candles)}<{min_history_days}")

    dates = [c.trade_date for c in candles]
    if len(dates) != len(set(dates)):
        issues.append("duplicate_trade_dates")

    if dates != sorted(dates):
        issues.append("unsorted_candles")

    for c in candles:
        if c.high < c.low:
            issues.append(f"high_lt_low:{c.trade_date}")
        if c.close <= 0 or c.open <= 0:
            issues.append(f"non_positive_price:{c.trade_date}")
        if c.volume < 0:
            issues.append(f"negative_volume:{c.trade_date}")
        if not (c.low <= c.open <= c.high) or not (c.low <= c.close <= c.high):
            issues.append(f"ohlc_out_of_range:{c.trade_date}")

    if candles:
        latest = candles[-1].trade_date
        staleness_days = (dt.date.today() - latest).days
        if staleness_days > 5:
            issues.append(f"stale_data:{staleness_days}d")

    return ValidationResult(is_valid=len(issues) == 0, issues=issues)


def is_penny_stock(last_close: float, min_price: float) -> bool:
    return last_close < min_price


def has_sufficient_liquidity(
    avg_daily_volume: float,
    avg_daily_turnover: float,
    min_volume: float,
    min_turnover: float,
) -> bool:
    return avg_daily_volume >= min_volume and avg_daily_turnover >= min_turnover
