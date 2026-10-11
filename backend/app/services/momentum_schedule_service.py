"""Scheduling guard logic for the Momentum Scanner automation.

Same "never fabricate a missing run" contract as
research_snapshot_service.resolve_collection_slot(): if the process isn't
running at a configured time (or on a real NSE trading day), the slot is
simply never scanned -- nothing here backdates or invents a run. Every
function takes an injectable `now_ist` rather than reading the clock
internally, so schedule logic is testable without real-clock dependence.
"""

import datetime as dt

from app.config import Settings, get_settings
from app.data.nse_holidays import is_nse_trading_day

EOD_SLOT_LABEL = "EOD"


def configured_intraday_slots(settings: Settings) -> list[dt.time]:
    slots = []
    for raw in settings.momentum_scan_slots_ist.split(","):
        raw = raw.strip()
        if not raw:
            continue
        hour, minute = raw.split(":")
        slots.append(dt.time(int(hour), int(minute)))
    return slots


def configured_eod_slot(settings: Settings) -> dt.time:
    hour, minute = settings.momentum_scan_eod_time_ist.strip().split(":")
    return dt.time(int(hour), int(minute))


def is_momentum_scan_day(now_ist: dt.datetime) -> bool:
    return is_nse_trading_day(now_ist.date())


def resolve_momentum_slot(now_ist: dt.datetime, settings: Settings | None = None) -> str | None:
    """Returns the configured slot label ("10:30" or "EOD") `now_ist` falls
    within `momentum_scan_slot_tolerance_minutes` of, or None if it matches
    no configured slot. Does not itself check is_momentum_scan_day -- callers
    (momentum_scan_service) check that separately so the two concerns stay
    testable independently."""
    settings = settings or get_settings()
    tolerance = dt.timedelta(minutes=settings.momentum_scan_slot_tolerance_minutes)
    today_midnight = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    for slot in configured_intraday_slots(settings):
        slot_dt = today_midnight.replace(hour=slot.hour, minute=slot.minute)
        if abs(now_ist - slot_dt) <= tolerance:
            return f"{slot.hour:02d}:{slot.minute:02d}"

    eod = configured_eod_slot(settings)
    eod_dt = today_midnight.replace(hour=eod.hour, minute=eod.minute)
    if abs(now_ist - eod_dt) <= tolerance:
        return EOD_SLOT_LABEL

    return None
