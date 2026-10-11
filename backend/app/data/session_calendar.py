"""Trading-session arithmetic for suggestion lifecycles (Phase A).

Counts real NSE trading sessions (weekday + published holiday list, see
nse_holidays.py) rather than calendar days. Any date beyond the holiday
list's LAST_VERIFIED_YEAR is only weekday-checked, so results that cross it
are returned with verified=False -- callers persist that flag instead of
silently trusting the date.

MCX sessions/holidays are NOT verified (see the Phase A audit) and have no
calendar here yet.
"""

import datetime as dt

from app.data.nse_holidays import LAST_VERIFIED_YEAR, is_nse_trading_day


def nth_nse_session_after(start: dt.date, n: int) -> tuple[dt.date, bool]:
    """The n-th NSE trading session strictly after `start` (n >= 1), and
    whether every day walked was covered by the verified holiday list."""
    if n < 1:
        raise ValueError("n must be >= 1")
    verified = True
    current = start
    counted = 0
    while counted < n:
        current += dt.timedelta(days=1)
        if current.year > LAST_VERIFIED_YEAR:
            verified = False
        if is_nse_trading_day(current):
            counted += 1
    return current, verified
