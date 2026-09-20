"""Volume / accumulation engine (section 8).

Produces measurable volume evidence and an `accumulation_score`. Deliberately
does NOT claim institutional buying -- that interpretation, combined with
other proxies, belongs to institutional_footprint_engine.py.
"""

import pandas as pd

from app.data.internal_models import Candle
from app.schemas.common import EvidenceItem


class VolumeResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _to_frame(candles: list[Candle]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [c.trade_date for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    )


def compute_volume_metrics(candles: list[Candle]) -> VolumeResult:
    if len(candles) < 20:
        return VolumeResult(
            volume_ratio=None, relative_volume=None, avg_volume_20d=None,
            high_volume_up_days_20d=None, high_volume_down_days_20d=None,
            consolidation_volume_avg=None, breakout_volume=None,
            accumulation_score=None, evidence=[],
        )

    df = _to_frame(candles)
    df["price_chg_pct"] = df["close"].pct_change() * 100
    df["avg_vol_20"] = df["volume"].rolling(20).mean()

    last = df.iloc[-1]
    avg_volume_20d = float(df["volume"].tail(20).mean())
    last_volume = float(last["volume"])
    volume_ratio = last_volume / avg_volume_20d if avg_volume_20d else None
    relative_volume = volume_ratio  # alias: relative to own 20d average (no market-wide feed yet)

    recent20 = df.tail(20).copy()
    high_vol_threshold = recent20["avg_vol_20"].iloc[-1] * 1.5 if not recent20["avg_vol_20"].isna().all() else None

    high_volume_up_days = 0
    high_volume_down_days = 0
    if high_vol_threshold:
        for _, row in recent20.iterrows():
            if row["volume"] >= high_vol_threshold:
                if row["price_chg_pct"] > 0:
                    high_volume_up_days += 1
                elif row["price_chg_pct"] < 0:
                    high_volume_down_days += 1

    # "Consolidation" days: small daily range in price, proxied by |chg%| < 1
    consolidation_days = recent20[recent20["price_chg_pct"].abs() < 1.0]
    consolidation_volume_avg = (
        float(consolidation_days["volume"].mean()) if not consolidation_days.empty else None
    )

    breakout_volume = float(last_volume) if volume_ratio and volume_ratio >= 1.5 else None

    evidence: list[EvidenceItem] = []
    if volume_ratio is not None:
        evidence.append(
            EvidenceItem(
                label="Volume vs 20D average",
                detail=f"Latest volume is {volume_ratio:.2f}x the 20-day average",
                value=round(volume_ratio, 3),
                is_positive=volume_ratio >= 1.2,
            )
        )
    evidence.append(
        EvidenceItem(
            label="High-volume up days (20D)",
            detail=f"{high_volume_up_days} sessions with >=1.5x average volume on an up day",
            value=high_volume_up_days,
            is_positive=high_volume_up_days > high_volume_down_days,
        )
    )
    evidence.append(
        EvidenceItem(
            label="High-volume down days (20D)",
            detail=f"{high_volume_down_days} sessions with >=1.5x average volume on a down day",
            value=high_volume_down_days,
            is_positive=high_volume_down_days < high_volume_up_days,
        )
    )

    # accumulation_score: 0-100, built only from the measurable components above.
    net_hv_days = high_volume_up_days - high_volume_down_days
    score = 50.0
    score += min(max(net_hv_days, -5), 5) * 6  # +/-6 pts per net high-volume up day, capped
    if volume_ratio is not None:
        score += min(max(volume_ratio - 1, -1), 1) * 15  # +/-15 pts for ratio deviation from 1x
    score = max(0.0, min(100.0, score))

    return VolumeResult(
        volume_ratio=round(volume_ratio, 3) if volume_ratio is not None else None,
        relative_volume=round(relative_volume, 3) if relative_volume is not None else None,
        avg_volume_20d=round(avg_volume_20d, 2),
        high_volume_up_days_20d=high_volume_up_days,
        high_volume_down_days_20d=high_volume_down_days,
        consolidation_volume_avg=round(consolidation_volume_avg, 2) if consolidation_volume_avg else None,
        breakout_volume=breakout_volume,
        accumulation_score=round(score, 2),
        evidence=evidence,
    )
