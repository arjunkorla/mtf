"""Data quality engine (section 25). Every scanner result carries this.

If critical data (price history) is missing, callers must reject the
candidate outright (see services/scanner_service.py) rather than let this
engine manufacture a score.
"""

import datetime as dt

from app.schemas.common import DataQuality

# Relative weight of each tracked source when computing the 0-100 quality score.
_SOURCE_WEIGHTS = {
    "price_history": 0.4,
    "volume_metrics": 0.2,
    "fno_metrics": 0.15,
    "fundamentals": 0.1,
    "news": 0.05,
    "sector_metrics": 0.1,
}


def compute_data_quality(
    source_timestamps: dict[str, dt.datetime],
    available_sources: set[str],
    stale_threshold_days: int = 5,
) -> DataQuality:
    missing: list[str] = []
    stale: list[str] = []
    now = dt.datetime.now(dt.UTC)

    score = 0.0
    for source, weight in _SOURCE_WEIGHTS.items():
        if source not in available_sources:
            missing.append(source)
            continue
        ts = source_timestamps.get(source)
        if ts is not None and (now - ts).days > stale_threshold_days:
            stale.append(source)
            score += weight * 0.5  # stale data counts as half-credit, not full or zero
        else:
            score += weight

    return DataQuality(
        data_quality_score=round(score * 100, 2),
        missing_data=missing,
        stale_data=stale,
        source_timestamps=source_timestamps,
    )
