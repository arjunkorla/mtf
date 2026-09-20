"""F&O engine (section 11): classifies observable futures price/OI behaviour
into the four textbook proxy patterns. This is an interpretation of market
data, not a claim about trader identity or intent.

  price up   + OI up    -> LONG_BUILDUP_PROXY
  price down + OI up    -> SHORT_BUILDUP_PROXY
  price up   + OI down  -> SHORT_COVERING_PROXY
  price down + OI down  -> LONG_UNWINDING_PROXY
"""

from app.core.constants import FnoPositioningProxy
from app.data.internal_models import FuturesContract
from app.schemas.common import EvidenceItem
from app.schemas.stock import FnoData


def classify_positioning(price_change_pct: float, oi_change_pct: float) -> FnoPositioningProxy:
    price_up = price_change_pct > 0.25
    price_down = price_change_pct < -0.25
    oi_up = oi_change_pct > 1.0
    oi_down = oi_change_pct < -1.0

    if price_up and oi_up:
        return FnoPositioningProxy.LONG_BUILDUP
    if price_down and oi_up:
        return FnoPositioningProxy.SHORT_BUILDUP
    if price_up and oi_down:
        return FnoPositioningProxy.SHORT_COVERING
    if price_down and oi_down:
        return FnoPositioningProxy.LONG_UNWINDING
    return FnoPositioningProxy.NEUTRAL


def compute_fno_metrics(
    is_fno_stock: bool,
    futures: FuturesContract | None,
    call_oi_total: float | None = None,
    put_oi_total: float | None = None,
) -> FnoData:
    if not is_fno_stock or futures is None:
        return FnoData(is_available=False, positioning_proxy=FnoPositioningProxy.NOT_AVAILABLE.value)

    # Real futures price change, from the resolved contract's own market
    # depth (Phase 1 F&O investigation) -- 0.0 only when the field is
    # genuinely absent, not fabricated as a default market view.
    price_change_pct = futures.price_change_pct if futures.price_change_pct is not None else 0.0
    oi_change_pct = futures.oi_change_pct if futures.oi_change_pct is not None else 0.0

    proxy = classify_positioning(price_change_pct, oi_change_pct)

    pcr = None
    if call_oi_total and put_oi_total and call_oi_total > 0:
        pcr = round(put_oi_total / call_oi_total, 3)

    evidence = [
        EvidenceItem(
            label="Futures OI change",
            detail=f"Open interest changed {oi_change_pct:.2f}% vs prior session",
            value=round(oi_change_pct, 2),
            is_positive=proxy in (FnoPositioningProxy.LONG_BUILDUP, FnoPositioningProxy.SHORT_COVERING),
        )
    ]
    if pcr is not None:
        evidence.append(
            EvidenceItem(
                label="Put/Call OI ratio",
                detail=f"PCR (OI) at {pcr:.2f}",
                value=pcr,
                is_positive=None,
            )
        )

    return FnoData(
        is_available=True,
        futures_price_change_pct=round(price_change_pct, 3),
        futures_oi_change_pct=round(oi_change_pct, 3),
        put_call_oi_ratio=pcr,
        positioning_proxy=proxy.value,
        evidence=evidence,
    )
