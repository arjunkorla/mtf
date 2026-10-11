"""Enums for the shared suggestion tracker (Phase A). Kept separate from
app/core/constants.py, which holds production MTF scoring configuration.

Lifecycle STATUS and OUTCOME are deliberately separate columns: status is
where the suggestion is in its lifecycle, outcome is the research verdict
once it is terminal. There is no CLOSED status -- a terminal status plus
closed_at expresses closure.
"""

from enum import StrEnum


class ScannerType(StrEnum):
    MTF = "MTF"
    INTRADAY = "INTRADAY"
    MCX = "MCX"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class SuggestionStatus(StrEnum):
    WAITING_ENTRY = "WAITING_ENTRY"
    ACTIVE = "ACTIVE"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    STOP_HIT = "STOP_HIT"
    INVALIDATED = "INVALIDATED"
    NO_ENTRY = "NO_ENTRY"
    EXPIRED = "EXPIRED"
    EXIT_BEFORE_CLOSE = "EXIT_BEFORE_CLOSE"
    CANCELLED = "CANCELLED"


OPEN_STATUSES = frozenset({SuggestionStatus.WAITING_ENTRY, SuggestionStatus.ACTIVE, SuggestionStatus.TARGET_1_HIT})
TERMINAL_STATUSES = frozenset(set(SuggestionStatus) - OPEN_STATUSES)


class SuggestionOutcome(StrEnum):
    PENDING = "PENDING"
    SUCCESS_TARGET_1 = "SUCCESS_TARGET_1"
    SUCCESS_TARGET_2 = "SUCCESS_TARGET_2"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"  # target 1 reached, then the ORIGINAL stop
    FAILED_STOP = "FAILED_STOP"
    NO_ENTRY = "NO_ENTRY"  # never a failed trade
    INVALIDATED_BEFORE_ENTRY = "INVALIDATED_BEFORE_ENTRY"  # never a failed trade
    EXPIRED = "EXPIRED"  # max holding reached without target 1 or stop
    EXIT_BEFORE_CLOSE = "EXIT_BEFORE_CLOSE"  # intraday cutoff without target 1 or stop
    CANCELLED = "CANCELLED"


class SuggestionEventType(StrEnum):
    SUGGESTION_CREATED = "SUGGESTION_CREATED"
    SIGNAL_REPEATED = "SIGNAL_REPEATED"  # duplicate scanner signal logged against the open suggestion
    ENTRY_TRIGGERED = "ENTRY_TRIGGERED"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    STOP_HIT = "STOP_HIT"
    INVALIDATED = "INVALIDATED"
    NO_ENTRY = "NO_ENTRY"
    EXPIRED = "EXPIRED"
    EXIT_BEFORE_CLOSE = "EXIT_BEFORE_CLOSE"
    CANCELLED = "CANCELLED"
    BREAKEVEN_REVISITED_AFTER_TARGET_1 = "BREAKEVEN_REVISITED_AFTER_TARGET_1"  # study data only, no state change


class EntryRule(StrEnum):
    # Entry only on a genuine market observation made AFTER the suggestion
    # was generated -- being inside the zone at generation time is not an entry.
    FRESH_TOUCH_AFTER_CREATION = "FRESH_TOUCH_AFTER_CREATION"


class LevelQuality(StrEnum):
    VERIFIED_STRUCTURE = "VERIFIED_STRUCTURE"  # derived from real price structure (support/resistance/range)
    ATR_DERIVED = "ATR_DERIVED"  # derived from a real, computed ATR
    FALLBACK = "FALLBACK"  # placeholder (e.g. fixed % of price) -- never tradable
    UNAVAILABLE = "UNAVAILABLE"


TRADABLE_LEVEL_QUALITIES = frozenset({LevelQuality.VERIFIED_STRUCTURE, LevelQuality.ATR_DERIVED})


class ObservationSource(StrEnum):
    TICK = "TICK"  # ordered trade prints (e.g. LiveDataHub)
    QUOTE = "QUOTE"  # REST quote snapshot
    CANDLE_1M = "CANDLE_1M"
    CANDLE_5M = "CANDLE_5M"
    CANDLE_D = "CANDLE_D"
    MANUAL = "MANUAL"


class ObservedPriceBasis(StrEnum):
    """How an event's observed_market_price was established -- recorded so
    gaps and bar-level approximations are never mistaken for exact fills."""

    TICK = "TICK"  # an actual trade print
    GAP_OPEN = "GAP_OPEN"  # bar opened beyond the threshold: the open is the first observed price
    OPEN_IN_ZONE = "OPEN_IN_ZONE"  # bar opened inside the entry zone
    WITHIN_BAR_RANGE = "WITHIN_BAR_RANGE"  # threshold lies inside the bar's range; exact print not observed
    SESSION_CLOSE = "SESSION_CLOSE"
    LAST_OBSERVED = "LAST_OBSERVED"


class TrackingStatus(StrEnum):
    """Health of the tracker's evidence for one suggestion (Phase B). Kept
    apart from lifecycle status: a tracking problem never changes status or
    outcome -- missing data is never turned into a stop/target."""

    NOT_TRACKED = "NOT_TRACKED"  # tracker has not reconciled this suggestion yet
    TRACKING = "TRACKING"  # candle reconciliation is up to date
    STALE = "STALE"  # market data could not be fetched/validated; will retry
    AUTH_REQUIRED = "AUTH_REQUIRED"  # FYERS session expired: tracking paused, nothing inferred
    DATA_GAP = "DATA_GAP"  # a verified NSE session returned no candles; not skipped
    UNSUPPORTED = "UNSUPPORTED"  # no approved tracking rules for this scanner/market


class EvidenceMethod(StrEnum):
    """Which tracker layer produced an event (stored in event detail)."""

    CANDLE_RECONCILIATION = "CANDLE_RECONCILIATION"
    ORDERED_TICKS = "ORDERED_TICKS"  # resolved an ambiguous candle with ordered tick prints
    SESSION_CLOSE = "SESSION_CLOSE"


class CreationStatus(StrEnum):
    CREATED = "CREATED"
    DUPLICATE_OPEN = "DUPLICATE_OPEN"
    REJECTED_LEVELS = "REJECTED_LEVELS"
    REJECTED_DATA_QUALITY = "REJECTED_DATA_QUALITY"
    REJECTED_NO_LIFECYCLE_RULES = "REJECTED_NO_LIFECYCLE_RULES"


# Default coexistence group: at most one open suggestion per
# (scanner, instrument, direction). A future scanner may explicitly opt a
# genuinely different setup into its own group -- never implicitly.
DEFAULT_COEXISTENCE_GROUP = "PRIMARY"
