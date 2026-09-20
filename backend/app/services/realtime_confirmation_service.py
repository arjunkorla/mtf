"""Real-Time Confirmation Engine -- an evidence-based confirmation layer
beside the existing MTF scanner (section: realtime confirmation,
2026-09-20).

Answers "does current intraday market behavior support or contradict the
existing 1-4 week MTF setup?" It is explicitly NOT a replacement for, or a
modification of, the existing scanner score: scoring_engine.py is never
imported or touched here, and nothing in this module can change candidate
ranking or selection.

Data-availability honesty (Phase 1 audit, confirmed against the installed
FYERS SDK's own field-mapping file, not assumed):
  - The shared WebSocket connection runs in litemode (see websocket.py's
    _run_live), which the SDK's own map.json confirms delivers ONLY
    symbol/ltp/type -- no live volume, no avg_trade_price (FYERS' own
    running-average field, the closest thing to intraday VWAP). Per an
    explicit decision not to switch to full mode in this phase (a change
    to the already-verified shared WebSocket, judged out of scope here),
    Volume Acceleration falls back to the existing daily-bar volume_ratio
    (VolumeData, already computed by the scanner) rather than true
    intraday volume, and VWAP confirmation is always UNAVAILABLE:
    technical.vwap is a 20-day rolling approximation from daily candles
    (technical_engine.vwap_approx), not a true intraday session VWAP, and
    presenting it as one would misrepresent what it actually is.
  - Depth comes from market_data_service.get_live_depth (REST-polled,
    15s-cached), not a live WebSocket depth stream -- per an explicit
    decision to keep the existing Phase 6 REST-based depth rather than add
    a second FYERS WebSocket subscription type in this phase.

Persistence: a short, bounded (by count AND TTL) rolling history of past
confirmation-status observations per symbol, in Redis
(confirmation_history_key) -- never unlimited tick history.
"""

import datetime as dt

from app.config import Settings, get_settings
from app.core.constants import (
    CONFIRMATION_WEIGHTS,
    BreakoutRelation,
    ConfirmationDataQuality,
    ConfirmationStatus,
    DepthImbalanceLevel,
    FuturesPriceOiState,
    LiquidityCondition,
    PersistenceState,
    PriceZoneStatus,
    VolumeAcceleration,
    VwapRelation,
)
from app.data.internal_models import MarketDepth
from app.db.redis_client import get_redis
from app.integrations.fyers.fyers_client import FyersClient
from app.schemas.common import EvidenceItem
from app.schemas.confirmation import (
    DepthConfirmationData,
    FuturesConfirmationData,
    PersistenceData,
    PriceConfirmationData,
    RealtimeConfirmationResponse,
    SpreadConditionData,
    VolumeConfirmationData,
    VwapConfirmationData,
)
from app.schemas.scanner import CandidateResponse
from app.services.cache_service import confirmation_history_key, get_json, set_json
from app.services.market_data_service import (
    classify_freshness,
    classify_market_status,
    get_cached_live_quote,
    get_live_depth,
    is_market_hours_ist,
)

_STATUS_ORDER = {
    ConfirmationStatus.CONTRADICTORY.value: 0,
    ConfirmationStatus.NEUTRAL.value: 1,
    ConfirmationStatus.SUPPORTIVE.value: 2,
    ConfirmationStatus.STRONGLY_SUPPORTIVE.value: 3,
}


# --- Phase 3: individual evidence signals -----------------------------------


def compute_price_confirmation(
    candidate: CandidateResponse, observed_price: float | None, settings: Settings
) -> PriceConfirmationData:
    entry_low = candidate.entry_zone_low
    entry_high = candidate.entry_zone_high
    invalidation = candidate.invalidation

    if observed_price is None:
        return PriceConfirmationData(
            status=PriceZoneStatus.UNAVAILABLE.value,
            near_invalidation=None,
            breakout_relation=BreakoutRelation.UNAVAILABLE.value,
            observed_price=None,
            entry_zone_low=entry_low,
            entry_zone_high=entry_high,
            invalidation=invalidation,
        )

    if observed_price > entry_high:
        status = PriceZoneStatus.ABOVE_ENTRY_ZONE
    elif observed_price < entry_low:
        status = PriceZoneStatus.BELOW_ENTRY_ZONE
    else:
        status = PriceZoneStatus.INSIDE_ENTRY_ZONE

    near_invalidation = False
    if invalidation:
        distance_pct = abs(observed_price - invalidation) / invalidation * 100
        near_invalidation = distance_pct <= settings.confirmation_near_invalidation_pct

    # Use the scanner's own existing levels -- never invent a new breakout price.
    breakout_level = candidate.technical.recent_high_20d or candidate.technical.resistance_level
    if breakout_level is None:
        breakout_relation = BreakoutRelation.UNAVAILABLE
    elif observed_price > breakout_level:
        breakout_relation = BreakoutRelation.ABOVE_BREAKOUT_LEVEL
    else:
        breakout_relation = BreakoutRelation.BELOW_BREAKOUT_LEVEL

    return PriceConfirmationData(
        status=status.value,
        near_invalidation=near_invalidation,
        breakout_relation=breakout_relation.value,
        observed_price=observed_price,
        entry_zone_low=entry_low,
        entry_zone_high=entry_high,
        invalidation=invalidation,
    )


def compute_volume_confirmation(candidate: CandidateResponse, settings: Settings) -> VolumeConfirmationData:
    """Uses the scanner's existing daily volume_ratio (VolumeData) -- see
    module docstring for why true intraday volume isn't available yet."""
    ratio = candidate.volume.volume_ratio
    if ratio is None:
        return VolumeConfirmationData(status=VolumeAcceleration.INSUFFICIENT_DATA.value, volume_ratio=None)

    if ratio >= settings.confirmation_volume_expanding_ratio:
        status = VolumeAcceleration.EXPANDING
    elif ratio <= settings.confirmation_volume_declining_ratio:
        status = VolumeAcceleration.DECLINING
    else:
        status = VolumeAcceleration.NORMAL

    return VolumeConfirmationData(status=status.value, volume_ratio=ratio)


def compute_vwap_confirmation() -> VwapConfirmationData:
    """Always UNAVAILABLE today -- no true intraday VWAP source exists (see
    module docstring). A separate function (not inlined) so the single
    reason lives in one place and this is trivially replaced if the
    lite/full-mode decision is revisited later."""
    return VwapConfirmationData(
        status=VwapRelation.UNAVAILABLE.value,
        reason_unavailable=(
            "No true intraday VWAP source is currently available: the live WebSocket feed runs in "
            "litemode (symbol/ltp/type only, no avg_trade_price), and technical.vwap is a 20-day "
            "rolling approximation from daily candles, not a session VWAP."
        ),
    )


def compute_depth_confirmation(depth: MarketDepth | None, settings: Settings) -> DepthConfirmationData:
    """depth_imbalance = (bid_qty_total - ask_qty_total) / (bid_qty_total + ask_qty_total),
    summed across the visible bid/ask levels FYERS actually returned (up to
    5 each). An order-book condition only -- see module-level warning in
    the API route and frontend copy: never institutional-buying proof."""
    if depth is None or (not depth.bid_levels and not depth.ask_levels):
        return DepthConfirmationData(status=DepthImbalanceLevel.UNAVAILABLE.value)

    # Phase 15 hardening: a real order-book quantity can never be negative
    # -- a negative value can only mean malformed/corrupted upstream data,
    # never a genuine "negative interest." Clamping each level to >= 0
    # before summing is what keeps depth_imbalance mathematically bounded
    # to [-1, +1] as required; without this, a single corrupted level can
    # push the ratio arbitrarily far outside that range (reproduced: a
    # single bid level with quantity=-100 alongside a normal ask level
    # produced imbalance=3.0, misclassified as STRONG_BID).
    bid_total = sum(max(0, lvl.quantity or 0) for lvl in depth.bid_levels)
    ask_total = sum(max(0, lvl.quantity or 0) for lvl in depth.ask_levels)

    # Phase 3/5 hardening: cross-check against FYERS' own totals. Verified
    # live (2026-09-20, 6 real symbols) that these should match exactly --
    # a mismatch would mean either our normalization or FYERS' own
    # totalbuyqty/totalsellqty semantics changed, worth surfacing rather
    # than silently trusting one side.
    ladder_totals_consistent = None
    if depth.total_buy_qty is not None and depth.total_sell_qty is not None:
        ladder_totals_consistent = depth.total_buy_qty == bid_total and depth.total_sell_qty == ask_total

    denom = bid_total + ask_total
    if denom == 0:
        return DepthConfirmationData(
            status=DepthImbalanceLevel.UNAVAILABLE.value, bid_quantity_total=bid_total, ask_quantity_total=ask_total,
            ladder_totals_consistent=ladder_totals_consistent,
        )

    imbalance = (bid_total - ask_total) / denom

    if imbalance >= settings.confirmation_depth_strong_threshold:
        status = DepthImbalanceLevel.STRONG_BID
    elif imbalance >= settings.confirmation_depth_moderate_threshold:
        status = DepthImbalanceLevel.MODERATE_BID
    elif imbalance <= -settings.confirmation_depth_strong_threshold:
        status = DepthImbalanceLevel.STRONG_ASK
    elif imbalance <= -settings.confirmation_depth_moderate_threshold:
        status = DepthImbalanceLevel.MODERATE_ASK
    else:
        status = DepthImbalanceLevel.BALANCED

    return DepthConfirmationData(
        status=status.value, bid_quantity_total=bid_total, ask_quantity_total=ask_total,
        depth_imbalance=round(imbalance, 4), ladder_totals_consistent=ladder_totals_consistent,
    )


def compute_spread_condition(depth: MarketDepth | None, settings: Settings) -> SpreadConditionData:
    """Liquidity/data-quality condition, never a directional signal."""
    if depth is None or depth.top_bid is None or depth.top_ask is None or depth.spread is None:
        return SpreadConditionData(status=LiquidityCondition.UNAVAILABLE.value)

    mid = (depth.top_bid + depth.top_ask) / 2
    if mid <= 0:
        return SpreadConditionData(status=LiquidityCondition.UNAVAILABLE.value, spread=depth.spread)

    spread_pct = (depth.spread / mid) * 100
    status = LiquidityCondition.WIDE if spread_pct > settings.confirmation_spread_wide_pct else LiquidityCondition.HEALTHY

    return SpreadConditionData(status=status.value, spread=round(depth.spread, 4), spread_percentage=round(spread_pct, 4))


def compute_futures_confirmation(candidate: CandidateResponse, settings: Settings) -> FuturesConfirmationData:
    """Purely descriptive price/OI relationship -- e.g. "price and open
    interest both increased," never "confirmed long buildup." The existing
    positioning_proxy (already labeled a proxy elsewhere in the scanner) is
    carried through as informational context only, not re-derived here."""
    fno = candidate.fno
    if not fno.is_available or fno.futures_price_change_pct is None or fno.futures_oi_change_pct is None:
        return FuturesConfirmationData(status=FuturesPriceOiState.UNAVAILABLE.value)

    price_chg = fno.futures_price_change_pct
    oi_chg = fno.futures_oi_change_pct
    threshold = settings.confirmation_futures_flat_threshold_pct

    price_up = price_chg > threshold
    price_down = price_chg < -threshold
    oi_up = oi_chg > threshold
    oi_down = oi_chg < -threshold

    if price_up and oi_up:
        status = FuturesPriceOiState.PRICE_UP_OI_UP
    elif price_up and oi_down:
        status = FuturesPriceOiState.PRICE_UP_OI_DOWN
    elif price_down and oi_up:
        status = FuturesPriceOiState.PRICE_DOWN_OI_UP
    elif price_down and oi_down:
        status = FuturesPriceOiState.PRICE_DOWN_OI_DOWN
    else:
        status = FuturesPriceOiState.FLAT

    return FuturesConfirmationData(
        status=status.value, futures_price_change_pct=price_chg, futures_oi_change_pct=oi_chg,
        positioning_proxy=fno.positioning_proxy,
    )


async def _load_persistence_history(redis, symbol: str) -> list[dict]:
    data = await get_json(redis, confirmation_history_key(symbol))
    return data.get("observations", []) if data else []


async def _save_persistence_history(redis, symbol: str, observations: list[dict], settings: Settings) -> None:
    await set_json(
        redis, confirmation_history_key(symbol), {"observations": observations}, settings.confirmation_persistence_ttl_seconds
    )


def compute_persistence(
    history: list[dict], current_status: str, settings: Settings
) -> tuple[PersistenceData, list[dict]]:
    """Appends `current_status` to the (already-loaded) history, trims to
    the configured window, and classifies the trend. Returns the
    classification plus the UPDATED history the caller must persist."""
    now = dt.datetime.now(dt.UTC).isoformat()
    updated = [*history, {"status": current_status, "as_of": now}]
    updated = updated[-settings.confirmation_persistence_window :]

    count = len(updated)
    first_status = updated[0]["status"]
    latest_status = updated[-1]["status"]

    if count < 2:
        state = PersistenceState.INSUFFICIENT_OBSERVATIONS
    else:
        first_rank = _STATUS_ORDER.get(first_status, 1)
        latest_rank = _STATUS_ORDER.get(latest_status, 1)
        if latest_rank > first_rank:
            state = PersistenceState.STRENGTHENING
        elif latest_rank < first_rank:
            state = PersistenceState.WEAKENING
        elif latest_status == current_status and all(o["status"] == current_status for o in updated):
            state = PersistenceState.PERSISTED
        else:
            state = PersistenceState.PERSISTED

    return (
        PersistenceData(
            status=state.value,
            observation_count=count,
            window=settings.confirmation_persistence_window,
            first_observed_status=first_status,
            latest_status=latest_status,
        ),
        updated,
    )


# --- Phase 4: data quality ---------------------------------------------------


def compute_data_quality(
    quote_freshness: str,
    depth_status: str,
    futures_status: str,
    persistence: PersistenceData,
    market_open: bool = True,
) -> str:
    """`market_open` defaults to True so every pre-existing caller/test
    keeps its exact prior behavior (backward compatible, Phase 6
    hardening). When explicitly False, HIGH is never returned: a closed
    market cannot provide genuine intraday confirmation regardless of how
    fresh our own cache happens to be -- the underlying signals only
    reflect the last available snapshot, not live evidence accumulating
    right now."""
    if quote_freshness == "UNAVAILABLE":
        return ConfirmationDataQuality.INSUFFICIENT_DATA.value

    depth_ok = depth_status != DepthImbalanceLevel.UNAVAILABLE.value
    futures_ok = futures_status != FuturesPriceOiState.UNAVAILABLE.value
    persistence_ok = persistence.status != PersistenceState.INSUFFICIENT_OBSERVATIONS.value

    if quote_freshness == "LIVE" and depth_ok and futures_ok and persistence_ok:
        return ConfirmationDataQuality.HIGH.value if market_open else ConfirmationDataQuality.MEDIUM.value
    if quote_freshness == "LIVE":
        return ConfirmationDataQuality.MEDIUM.value
    return ConfirmationDataQuality.LOW.value  # quote is STALE


# --- Phase 5: confirmation score (experimental) ------------------------------

_COMPONENT_SCORERS = {
    "price": lambda p: (
        None
        if p.status == PriceZoneStatus.UNAVAILABLE.value
        else max(
            0.0,
            (
                85.0
                if p.status == PriceZoneStatus.ABOVE_ENTRY_ZONE.value
                else 65.0
                if p.status == PriceZoneStatus.INSIDE_ENTRY_ZONE.value
                else 20.0
            )
            - (30.0 if p.near_invalidation else 0.0),
        )
    ),
    "volume": lambda v: {"EXPANDING": 100.0, "NORMAL": 50.0, "DECLINING": 0.0}.get(v.status),
    "vwap": lambda vw: {"ABOVE_VWAP": 100.0, "NEAR_VWAP": 50.0, "BELOW_VWAP": 0.0}.get(vw.status),
    "depth": lambda d: {
        "STRONG_BID": 100.0, "MODERATE_BID": 75.0, "BALANCED": 50.0, "MODERATE_ASK": 25.0, "STRONG_ASK": 0.0,
    }.get(d.status),
    "futures": lambda f: {
        "PRICE_UP_OI_UP": 100.0, "PRICE_UP_OI_DOWN": 60.0, "FLAT": 50.0,
        "PRICE_DOWN_OI_UP": 25.0, "PRICE_DOWN_OI_DOWN": 40.0,
    }.get(f.status),
    "persistence": lambda p: {
        "STRENGTHENING": 100.0, "PERSISTED": 70.0, "INSUFFICIENT_OBSERVATIONS": 50.0,
        "WEAKENING": 20.0, "DISAPPEARED": 0.0,
    }.get(p.status),
}


def compute_confirmation_score(
    price: PriceConfirmationData,
    volume: VolumeConfirmationData,
    vwap: VwapConfirmationData,
    depth: DepthConfirmationData,
    futures: FuturesConfirmationData,
    persistence: PersistenceData,
) -> float | None:
    """Re-normalizes against whichever components are actually available,
    same pattern as scoring_engine.compute_score -- so an UNAVAILABLE VWAP
    (currently always the case) never silently counts as zero."""
    inputs = {"price": price, "volume": volume, "vwap": vwap, "depth": depth, "futures": futures, "persistence": persistence}
    available_weight = 0.0
    weighted_sum = 0.0
    for name, obj in inputs.items():
        component_score = _COMPONENT_SCORERS[name](obj)
        if component_score is None:
            continue
        weight = CONFIRMATION_WEIGHTS[name]
        available_weight += weight
        weighted_sum += component_score * weight

    if available_weight == 0:
        return None
    return round(weighted_sum / available_weight, 2)


def classify_confirmation(score: float | None, data_quality: str) -> str:
    if data_quality == ConfirmationDataQuality.INSUFFICIENT_DATA.value or score is None:
        return ConfirmationStatus.INSUFFICIENT_DATA.value
    if score >= 75:
        return ConfirmationStatus.STRONGLY_SUPPORTIVE.value
    if score >= 55:
        return ConfirmationStatus.SUPPORTIVE.value
    if score >= 45:
        return ConfirmationStatus.NEUTRAL.value
    return ConfirmationStatus.CONTRADICTORY.value


# --- Orchestration ------------------------------------------------------------


def _build_evidence(price, volume, depth, spread, futures) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    if price.observed_price is not None:
        evidence.append(
            EvidenceItem(
                label="Price vs entry zone", detail=f"Observed price is {price.status.replace('_', ' ').lower()}",
                value=price.observed_price, is_positive=price.status == PriceZoneStatus.ABOVE_ENTRY_ZONE.value or None,
            )
        )
    if volume.volume_ratio is not None:
        evidence.append(
            EvidenceItem(
                label="Volume activity", detail=f"Latest completed session volume is {volume.volume_ratio:.2f}x the 20-day average",
                value=volume.volume_ratio, is_positive=volume.status == VolumeAcceleration.EXPANDING.value,
            )
        )
    if depth.depth_imbalance is not None:
        evidence.append(
            EvidenceItem(
                label="Depth imbalance", detail=f"bid quantity {'exceeded' if depth.depth_imbalance > 0 else 'trailed'} ask quantity",
                value=depth.depth_imbalance, is_positive=depth.depth_imbalance > 0,
            )
        )
    if spread.spread_percentage is not None:
        evidence.append(
            EvidenceItem(
                label="Spread", detail=f"Spread is {spread.spread_percentage:.3f}% of mid price ({spread.status.lower()})",
                value=spread.spread_percentage, is_positive=spread.status == LiquidityCondition.HEALTHY.value,
            )
        )
    if futures.futures_price_change_pct is not None:
        evidence.append(
            EvidenceItem(
                label="Futures price/OI", detail=futures.status.replace("_", " ").title(),
                value=futures.futures_oi_change_pct, is_positive=None,
            )
        )
    return evidence


def _build_warnings(depth, futures, spread, quote_freshness: str, market_status: str) -> list[str]:
    warnings: list[str] = []
    if market_status == "MARKET_CLOSED_LAST_AVAILABLE":
        warnings.append(
            "NSE is currently closed -- this reflects the last available snapshot, not live intraday "
            "trading activity. Depth and volume signals in particular may not represent genuine order flow."
        )
    if depth.status != DepthImbalanceLevel.UNAVAILABLE.value:
        warnings.append(
            "Market-depth conditions can change rapidly and reflect visible order-book orders only -- "
            "this is not evidence of institutional intent or a prediction of future price direction."
        )
    if depth.ladder_totals_consistent is False:
        warnings.append(
            "Depth ladder totals did not match FYERS' own reported totals for this symbol -- "
            "treat the depth reading with extra caution."
        )
    if futures.status != FuturesPriceOiState.UNAVAILABLE.value:
        warnings.append("Futures price/OI relationship is descriptive only, not confirmed positioning.")
    if spread.status == LiquidityCondition.WIDE.value:
        warnings.append("Spread is wide relative to price -- liquidity may be thin right now.")
    if quote_freshness != "LIVE":
        warnings.append(f"Underlying quote is {quote_freshness.lower()}, not live -- treat this confirmation cautiously.")
    return warnings


async def get_realtime_confirmation(
    symbol: str,
    candidate: CandidateResponse,
    client: FyersClient,
    settings: Settings | None = None,
) -> RealtimeConfirmationResponse:
    settings = settings or get_settings()
    redis = get_redis()

    # Phase 15 hardening: one instant, captured once, threaded through every
    # time-dependent call below -- previously freshness/market_open/
    # market_status each independently read dt.datetime.now(dt.UTC)
    # microseconds apart (three competing time sources for what should be
    # one consistent "now"). Harmless in practice at that timescale, but
    # exactly the anti-pattern this phase asked to check for.
    now_utc = dt.datetime.now(dt.UTC)

    cached_quote = await get_cached_live_quote(symbol)
    observed_price = cached_quote["ltp"] if cached_quote else None
    quote_as_of = dt.datetime.fromisoformat(cached_quote["as_of"]) if cached_quote else None
    freshness = classify_freshness(quote_as_of, now_utc=now_utc)
    market_open = is_market_hours_ist(now_utc)
    market_status = classify_market_status(quote_as_of, now_utc=now_utc)

    depth = await get_live_depth(client, symbol)

    price = compute_price_confirmation(candidate, observed_price, settings)
    volume = compute_volume_confirmation(candidate, settings)
    vwap = compute_vwap_confirmation()
    depth_confirmation = compute_depth_confirmation(depth, settings)
    spread = compute_spread_condition(depth, settings)
    futures = compute_futures_confirmation(candidate, settings)

    # Persistence needs *this* observation's overall status, which needs a
    # score/classification first -- but the score also feeds on persistence.
    # Resolve by classifying twice: once without persistence (to log this
    # observation), then again with the real persistence result.
    provisional_score = compute_confirmation_score(
        price, volume, vwap, depth_confirmation, futures,
        PersistenceData(status="INSUFFICIENT_OBSERVATIONS", observation_count=0, window=settings.confirmation_persistence_window),
    )
    provisional_quality = compute_data_quality(
        freshness, depth_confirmation.status, futures.status,
        PersistenceData(status="INSUFFICIENT_OBSERVATIONS", observation_count=0, window=settings.confirmation_persistence_window),
        market_open=market_open,
    )
    provisional_status = classify_confirmation(provisional_score, provisional_quality)

    history = await _load_persistence_history(redis, symbol)
    persistence, updated_history = compute_persistence(history, provisional_status, settings)
    await _save_persistence_history(redis, symbol, updated_history, settings)

    score = compute_confirmation_score(price, volume, vwap, depth_confirmation, futures, persistence)
    data_quality = compute_data_quality(freshness, depth_confirmation.status, futures.status, persistence, market_open=market_open)
    status = classify_confirmation(score, data_quality)

    evidence = _build_evidence(price, volume, depth_confirmation, spread, futures)
    warnings = _build_warnings(depth_confirmation, futures, spread, freshness, market_status)

    return RealtimeConfirmationResponse(
        symbol=symbol,
        timestamp=dt.datetime.now(dt.UTC),
        freshness=freshness,
        market_status=market_status,
        confirmation_status=status,
        confirmation_score=score,
        data_quality=data_quality,
        price_confirmation=price,
        volume_confirmation=volume,
        vwap_confirmation=vwap,
        depth_confirmation=depth_confirmation,
        spread_condition=spread,
        futures_confirmation=futures,
        persistence=persistence,
        evidence=evidence,
        warnings=warnings,
    )
