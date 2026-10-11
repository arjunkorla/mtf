"""FYERS order-margin ("span_margin") adapter, used to derive a per-symbol
required-MTF-margin percentage.

STATUS: NOT YET CONFIRMED LIVE (unlike quotes.py/fno.py's mock payloads,
which carry "confirmed live" dates -- see mock_responses.py's module
docstring). FYERS API v3 does not expose a dedicated "MTF eligibility"
lookup; the closest real, documented capability is the order-margin
calculator (v2 path: /api/v2/span_margin; v3 mirrors this under
TRADING_BASE_URL), which computes the margin required for a hypothetical
order basket. FYERS does support "MTF" as an order `productType` alongside
CNC/INTRADAY/MARGIN (public docs: "Margin Trading Facility (MTF) at
FYERS"), so requesting a 1-share hypothetical MTF order and comparing the
margin FYERS says is required against that order's notional value gives a
required-margin PERCENTAGE derived from real numbers -- not a fabricated
one.

This has not been exercised against a real FYERS account from this
environment (no live credentials available here). Before flipping
USE_MOCK_FYERS=false for this feature, run this adapter live against a
handful of real MTF-eligible symbols and confirm:
  1. the endpoint accepts a single-order basket with productType="MTF",
  2. the response's margin field represents total margin for THIS order
     (not a pre-existing-position-inclusive number), and
  3. a non-MTF-eligible symbol produces a clear rejection rather than a
     silently-wrong number.
Record the finding (see AGENTS.md Phase A). Until confirmed, treat any
value this returns with suspicion; the engine layer (mtf_leverage_engine.py)
is deliberately defensive and treats any unexpected shape as unverifiable
rather than guessing.
"""

from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.mock_responses import mock_margin_response
from app.logging_config import get_logger

logger = get_logger(__name__)

MARGIN_CALCULATOR_PATH = "/span_margin"


async def get_symbol_margin(client: FyersClient, symbol: str, ltp: float) -> dict | None:
    """Returns the raw FYERS margin-calculator response for a hypothetical
    1-share MTF order in `symbol` at `ltp`, or None if margin data cannot be
    confirmed for any reason. Never raises: one symbol's margin lookup
    failing must never break a scan (same contract as fno.py's adapters)."""
    if ltp is None or ltp <= 0:
        return None

    if client.use_mock:
        return mock_margin_response(symbol)

    payload = {
        "data": [
            {
                "symbol": symbol,
                "qty": 1,
                "side": 1,  # buy
                "type": 2,  # market order
                "productType": "MTF",
                "limitPrice": 0,
                "stopLoss": 0,
            }
        ]
    }
    try:
        return await client.post_trading(MARGIN_CALCULATOR_PATH, json=payload)
    except Exception as exc:  # noqa: BLE001 -- margin lookup failure must not break the scan
        logger.warning("FYERS margin lookup unavailable for %s: %s", symbol, exc)
        return None


def extract_required_margin_pct(margin_response: dict | None, ltp: float, qty: int = 1) -> float | None:
    """Parses `margin_response` (as returned by get_symbol_margin) into a
    required-margin PERCENTAGE. Deliberately defensive: an unrecognized
    shape returns None rather than guessing at a field name. Field names
    below (margin_total / marginTotal) are our best-effort mapping of the
    documented span_margin response and MUST be corrected once Phase A's
    live verification confirms the actual v3 field names."""
    if not margin_response or ltp is None or ltp <= 0:
        return None

    data = margin_response.get("data")
    if not data:
        return None

    margin_amount = None
    if isinstance(data, dict):
        margin_amount = data.get("margin_total") or data.get("marginTotal") or data.get("margin_new_order")
    elif isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            margin_amount = first.get("margin_total") or first.get("marginTotal") or first.get("margin")

    if margin_amount is None:
        return None

    try:
        margin_amount = float(margin_amount)
    except (TypeError, ValueError):
        return None

    notional = ltp * qty
    if notional <= 0:
        return None

    margin_pct = (margin_amount / notional) * 100
    if not (0 < margin_pct <= 100):
        return None

    return round(margin_pct, 4)
