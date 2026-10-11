"""Level-quality validation for tracked suggestions (Phase A).

A scanner result only becomes a tracked suggestion if its entry zone,
target 1 and stop come from legitimate market evidence. Every level arrives
tagged with a LevelQuality by the scanner-specific adapter that produced it
(the MTF adapter is a later, separately approved phase -- nothing here
classifies existing scenario_engine output). This module only enforces:

  - entry_low, entry_high, target_1, stop_loss: REQUIRED and must be
    VERIFIED_STRUCTURE or ATR_DERIVED. FALLBACK / UNAVAILABLE / missing ->
    the suggestion is rejected, with the reason returned.
  - target_2, invalidation_price: optional. A non-tradable one is EXCLUDED
    (not tracked) and the exclusion is recorded in level_notes -- never
    silently kept, never silently dropped.
  - Geometry must be coherent for the direction.
"""

from dataclasses import dataclass, field

from app.core.suggestion_constants import TRADABLE_LEVEL_QUALITIES, Direction, LevelQuality

REQUIRED_LEVELS = ("entry_low", "entry_high", "target_1", "stop_loss")
OPTIONAL_LEVELS = ("target_2", "invalidation_price")


@dataclass(frozen=True)
class LevelSpec:
    price: float | None
    quality: str
    provenance: str | None = None  # e.g. "20D swing low", "support - 0.25*ATR14"


@dataclass
class LevelValidationResult:
    accepted: bool
    levels: dict[str, float | None] = field(default_factory=dict)
    level_quality: dict[str, dict] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)  # why the suggestion was rejected
    notes: list[str] = field(default_factory=list)  # non-fatal exclusions


def _tradable(spec: LevelSpec | None) -> bool:
    return (
        spec is not None and spec.price is not None and spec.price > 0
        and spec.quality in {q.value for q in TRADABLE_LEVEL_QUALITIES}
    )


def validate_levels(direction: str, specs: dict[str, LevelSpec]) -> LevelValidationResult:
    result = LevelValidationResult(accepted=False)
    known_qualities = {q.value for q in LevelQuality}

    for name in (*REQUIRED_LEVELS, *OPTIONAL_LEVELS):
        spec = specs.get(name)
        if spec is not None and spec.quality not in known_qualities:
            result.reasons.append(f"{name}: unknown level quality {spec.quality!r}")
            continue
        result.level_quality[name] = {
            "quality": spec.quality if spec else LevelQuality.UNAVAILABLE.value,
            "price": spec.price if spec else None,
            "provenance": spec.provenance if spec else None,
        }

    for name in REQUIRED_LEVELS:
        spec = specs.get(name)
        if spec is None or spec.price is None:
            result.reasons.append(f"{name} is unavailable")
        elif not _tradable(spec):
            result.reasons.append(f"{name} has non-tradable quality {spec.quality} (price {spec.price})")
        else:
            result.levels[name] = float(spec.price)

    for name in OPTIONAL_LEVELS:
        spec = specs.get(name)
        if spec is None or spec.price is None:
            result.levels[name] = None
        elif _tradable(spec):
            result.levels[name] = float(spec.price)
        else:
            result.levels[name] = None
            result.notes.append(f"{name} excluded from tracking: quality {spec.quality} is not tradable (price {spec.price})")

    if result.reasons:
        return result

    lv = result.levels
    lo, hi, t1, t2, stop, inv = lv["entry_low"], lv["entry_high"], lv["target_1"], lv["target_2"], lv["stop_loss"], lv["invalidation_price"]
    if lo > hi:
        result.reasons.append(f"entry_low {lo} is above entry_high {hi}")
    if direction == Direction.LONG.value:
        if not stop < lo:
            result.reasons.append(f"LONG stop {stop} must be below entry_low {lo}")
        if not t1 > hi:
            result.reasons.append(f"LONG target_1 {t1} must be above entry_high {hi}")
        if t2 is not None and not t2 > t1:
            result.reasons.append(f"LONG target_2 {t2} must be above target_1 {t1}")
        if inv is not None and not inv < lo:
            result.reasons.append(f"LONG invalidation {inv} must be below entry_low {lo}")
    elif direction == Direction.SHORT.value:
        if not stop > hi:
            result.reasons.append(f"SHORT stop {stop} must be above entry_high {hi}")
        if not t1 < lo:
            result.reasons.append(f"SHORT target_1 {t1} must be below entry_low {lo}")
        if t2 is not None and not t2 < t1:
            result.reasons.append(f"SHORT target_2 {t2} must be below target_1 {t1}")
        if inv is not None and not inv > hi:
            result.reasons.append(f"SHORT invalidation {inv} must be above entry_high {hi}")
    else:
        result.reasons.append(f"unknown direction {direction!r}")

    result.accepted = not result.reasons
    return result
