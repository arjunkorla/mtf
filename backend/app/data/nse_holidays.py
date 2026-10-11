"""NSE equity Capital Market segment trading holiday calendar.

This is a static, publicly-known calendar (NSE publishes trading holidays a
year in advance) -- not fabricated market data. The 2026 list below was
cross-checked against two independent published brokerage holiday calendars
(Zerodha, Groww) on 2026-09-25, which agreed exactly on all 15 dates
including the unusual Sunday, 2026-11-08 Muhurat trading session for Diwali
Laxmi Pujan (not itself a holiday, so not listed here). Before relying on
this for real automated trading-day gating, cross-check against NSE's own
published circular (nseindia.com/resources/exchange-communication-holidays)
-- this module's list has NOT been verified against that primary source
directly (the exchange's own site could not be fetched from this
environment).

`is_nse_trading_day()` falls back to a weekday-only check with a loud
warning for any year beyond LAST_VERIFIED_YEAR, rather than silently
guessing -- this calendar requires an annual update and that must not be
forgotten silently.
"""

import datetime as dt

from app.logging_config import get_logger

logger = get_logger(__name__)

LAST_VERIFIED_YEAR = 2026

NSE_TRADING_HOLIDAYS: dict[int, set[dt.date]] = {
    2026: {
        dt.date(2026, 1, 26),  # Republic Day
        dt.date(2026, 3, 3),  # Holi
        dt.date(2026, 3, 26),  # Shri Ram Navami
        dt.date(2026, 3, 31),  # Shri Mahavir Jayanti
        dt.date(2026, 4, 3),  # Good Friday
        dt.date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
        dt.date(2026, 5, 1),  # Maharashtra Day
        dt.date(2026, 5, 28),  # Bakri Id
        dt.date(2026, 6, 26),  # Muharram
        dt.date(2026, 9, 14),  # Ganesh Chaturthi
        dt.date(2026, 10, 2),  # Mahatma Gandhi Jayanti
        dt.date(2026, 10, 20),  # Dussehra
        dt.date(2026, 11, 10),  # Diwali-Balipratipada
        dt.date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
        dt.date(2026, 12, 25),  # Christmas
    },
}


def is_nse_trading_day(d: dt.date) -> bool:
    """Weekday check + explicit holiday-list check. Years beyond
    LAST_VERIFIED_YEAR fall back to weekday-only with a warning, rather than
    silently assuming no holidays exist that year."""
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    if d.year > LAST_VERIFIED_YEAR:
        logger.warning(
            "NSE holiday calendar not verified for year %s (last verified: %s) -- "
            "falling back to weekday-only check for %s. Update app/data/nse_holidays.py.",
            d.year, LAST_VERIFIED_YEAR, d,
        )
        return True

    return d not in NSE_TRADING_HOLIDAYS.get(d.year, set())
