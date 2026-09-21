"""India VIX risk-regime classification (research layer, Phase 5).

Static bands, NOT backtested for this project's universe -- documented
basis: India VIX (NSE-published) has historically traded roughly in a
10-35 range over multi-year periods, with sub-12 commonly described in
market commentary as a calm/low-volatility regime and 25-30+ as a
stressed/elevated one. These are widely-cited descriptive bands, not
statistically derived or validated thresholds for this project -- a
starting point to make explicit and configurable, not a claim of
precision.

By design (see research_confirmation_engine.py), VIX affects RISK CONTEXT
and CONFIDENCE only -- it is never a weighted, bullish/bearish score
component. Trend (RISING/FALLING) is deliberately not classified: this
system has no persisted VIX history, so calling a trend from one live
snapshot would be a fabricated trend, not measured evidence.
"""

from app.core.constants import VixRegime

VIX_LOW_THRESHOLD = 12.0
VIX_ELEVATED_THRESHOLD = 20.0
VIX_HIGH_THRESHOLD = 30.0


def classify_vix_regime(vix: float | None) -> str:
    if vix is None:
        return VixRegime.INSUFFICIENT_DATA.value
    if vix < VIX_LOW_THRESHOLD:
        return VixRegime.LOW_VOLATILITY.value
    if vix < VIX_ELEVATED_THRESHOLD:
        return VixRegime.NORMAL.value
    if vix < VIX_HIGH_THRESHOLD:
        return VixRegime.ELEVATED.value
    return VixRegime.HIGH.value
