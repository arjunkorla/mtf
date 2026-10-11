import datetime as dt

from app.config import Settings
from app.services.momentum_schedule_service import (
    EOD_SLOT_LABEL,
    is_momentum_scan_day,
    resolve_momentum_slot,
)


def _settings() -> Settings:
    return Settings(
        momentum_scan_slots_ist="09:20,10:30,12:30,14:30,15:15",
        momentum_scan_eod_time_ist="16:00",
        momentum_scan_slot_tolerance_minutes=5,
    )


def test_resolve_slot_within_tolerance():
    now_ist = dt.datetime(2026, 9, 28, 10, 33)  # a Monday
    assert resolve_momentum_slot(now_ist, _settings()) == "10:30"


def test_resolve_slot_outside_tolerance_returns_none():
    now_ist = dt.datetime(2026, 9, 28, 11, 0)
    assert resolve_momentum_slot(now_ist, _settings()) is None


def test_resolve_eod_slot():
    now_ist = dt.datetime(2026, 9, 28, 16, 2)
    assert resolve_momentum_slot(now_ist, _settings()) == EOD_SLOT_LABEL


def test_is_momentum_scan_day_true_on_regular_weekday():
    assert is_momentum_scan_day(dt.datetime(2026, 9, 28)) is True  # Monday


def test_is_momentum_scan_day_false_on_weekend():
    assert is_momentum_scan_day(dt.datetime(2026, 9, 27)) is False  # Sunday


def test_is_momentum_scan_day_false_on_known_nse_holiday():
    assert is_momentum_scan_day(dt.datetime(2026, 1, 26)) is False  # Republic Day


def test_is_momentum_scan_day_beyond_verified_year_falls_back_to_weekday(caplog):
    # 2030-01-01 is a Tuesday -- beyond LAST_VERIFIED_YEAR, so this exercises
    # the loud weekday-only fallback rather than a silent guess.
    assert is_momentum_scan_day(dt.datetime(2030, 1, 1)) is True
