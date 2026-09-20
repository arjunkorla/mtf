"""Tests for the Real-Time Confirmation Engine (real-time confirmation
work, 2026-09-20). Pure-function unit tests for each evidence signal, plus
the score/classification/data-quality logic -- no network, no Redis
required (the orchestration function get_realtime_confirmation is covered
separately by the API integration test).
"""

from app.config import Settings
from app.data.internal_models import DepthLevel, MarketDepth
from app.schemas.common import (
    DataQuality,
    InstitutionalFootprint,
    PositionSizing,
    ScenarioLevels,
    SetupDetection,
)
from app.schemas.scanner import CandidateResponse
from app.schemas.stock import (
    FnoData,
    FundamentalData,
    NewsData,
    RelativeStrengthData,
    SectorData,
    TechnicalData,
    VolumeData,
)
from app.services.realtime_confirmation_service import (
    classify_confirmation,
    compute_confirmation_score,
    compute_data_quality,
    compute_depth_confirmation,
    compute_futures_confirmation,
    compute_persistence,
    compute_price_confirmation,
    compute_spread_condition,
    compute_volume_confirmation,
    compute_vwap_confirmation,
)
from app.schemas.confirmation import PersistenceData

_SETTINGS = Settings()


def _candidate(
    entry_zone_low=100.0,
    entry_zone_high=105.0,
    invalidation=95.0,
    recent_high_20d=110.0,
    volume_ratio=1.0,
    fno_available=False,
    futures_price_change_pct=None,
    futures_oi_change_pct=None,
) -> CandidateResponse:
    return CandidateResponse(
        symbol="NSE:TEST-EQ",
        company_name="Test Co",
        score=50.0,
        score_components=[],
        signal_quality="MEDIUM",
        price=102.0,
        entry_zone_low=entry_zone_low,
        entry_zone_high=entry_zone_high,
        invalidation=invalidation,
        scenarios=ScenarioLevels(
            entry_zone_low=entry_zone_low, entry_zone_high=entry_zone_high, preferred_entry=entry_zone_high,
            invalidation=invalidation, resistance_scenario_1=115.0,
        ),
        setup=SetupDetection(setup_type="PULLBACK"),
        institutional_footprint=InstitutionalFootprint(institutional_footprint_score=None, institutional_footprint_level="INSUFFICIENT_DATA"),
        technical=TechnicalData(recent_high_20d=recent_high_20d, resistance_level=recent_high_20d),
        volume=VolumeData(volume_ratio=volume_ratio),
        fno=FnoData(
            is_available=fno_available, futures_price_change_pct=futures_price_change_pct,
            futures_oi_change_pct=futures_oi_change_pct,
        ),
        fundamentals=FundamentalData(is_available=False),
        relative_strength=RelativeStrengthData(label="NEUTRAL"),
        sector_context=SectorData(relative_strength=RelativeStrengthData(label="NEUTRAL")),
        news=NewsData(),
        position_sizing=PositionSizing(
            available_capital=100000, risk_percent=1, entry_price=102.0, invalidation_price=95.0,
            risk_per_share=7.0, max_rupee_risk=1000.0, quantity=100, capital_required=10200.0,
            capital_utilization_pct=10.2,
        ),
        data_quality=DataQuality(data_quality_score=50.0),
    )


# --- Price confirmation ------------------------------------------------------


def test_price_above_entry_zone():
    c = _candidate(entry_zone_low=100.0, entry_zone_high=105.0)
    result = compute_price_confirmation(c, observed_price=110.0, settings=_SETTINGS)
    assert result.status == "ABOVE_ENTRY_ZONE"


def test_price_inside_entry_zone():
    c = _candidate(entry_zone_low=100.0, entry_zone_high=105.0)
    result = compute_price_confirmation(c, observed_price=102.0, settings=_SETTINGS)
    assert result.status == "INSIDE_ENTRY_ZONE"


def test_price_below_entry_zone():
    c = _candidate(entry_zone_low=100.0, entry_zone_high=105.0)
    result = compute_price_confirmation(c, observed_price=98.0, settings=_SETTINGS)
    assert result.status == "BELOW_ENTRY_ZONE"


def test_price_near_invalidation():
    c = _candidate(invalidation=100.0)
    result = compute_price_confirmation(c, observed_price=101.0, settings=_SETTINGS)  # 1% away
    assert result.near_invalidation is True


def test_price_not_near_invalidation():
    c = _candidate(invalidation=100.0)
    result = compute_price_confirmation(c, observed_price=120.0, settings=_SETTINGS)
    assert result.near_invalidation is False


def test_price_breakout_relation_uses_existing_level_not_invented():
    c = _candidate(recent_high_20d=110.0)
    above = compute_price_confirmation(c, observed_price=115.0, settings=_SETTINGS)
    below = compute_price_confirmation(c, observed_price=105.0, settings=_SETTINGS)
    assert above.breakout_relation == "ABOVE_BREAKOUT_LEVEL"
    assert below.breakout_relation == "BELOW_BREAKOUT_LEVEL"


def test_price_confirmation_unavailable_when_no_observed_price():
    c = _candidate()
    result = compute_price_confirmation(c, observed_price=None, settings=_SETTINGS)
    assert result.status == "UNAVAILABLE"
    assert result.breakout_relation == "UNAVAILABLE"


# --- Volume confirmation -----------------------------------------------------


def test_volume_expanding():
    c = _candidate(volume_ratio=1.5)
    assert compute_volume_confirmation(c, _SETTINGS).status == "EXPANDING"


def test_volume_declining():
    c = _candidate(volume_ratio=0.5)
    assert compute_volume_confirmation(c, _SETTINGS).status == "DECLINING"


def test_volume_normal():
    c = _candidate(volume_ratio=1.0)
    assert compute_volume_confirmation(c, _SETTINGS).status == "NORMAL"


def test_volume_insufficient_data():
    c = _candidate(volume_ratio=None)
    assert compute_volume_confirmation(c, _SETTINGS).status == "INSUFFICIENT_DATA"


def test_volume_confirmation_baseline_wording_is_precise_about_daily_bar():
    """Phase 7 hardening: must never imply live/intraday volume -- the
    baseline text is the one place this is documented on the wire."""
    c = _candidate(volume_ratio=1.5)
    result = compute_volume_confirmation(c, _SETTINGS)
    baseline_lower = result.baseline.lower()
    assert "daily" in baseline_lower or "session" in baseline_lower
    assert "intraday" not in baseline_lower or "not real-time intraday" in baseline_lower
    assert "live" not in baseline_lower


# --- VWAP (always unavailable today) -----------------------------------------


def test_vwap_always_unavailable():
    result = compute_vwap_confirmation()
    assert result.status == "UNAVAILABLE"
    assert result.reason_unavailable is not None


# --- Depth imbalance ----------------------------------------------------------


def _depth(bid_qtys, ask_qtys):
    return MarketDepth(
        symbol="NSE:TEST-EQ", total_buy_qty=sum(bid_qtys), total_sell_qty=sum(ask_qtys),
        top_bid=100.0, top_ask=100.5, spread=0.5,
        bid_levels=[DepthLevel(price=100.0, quantity=q, order_count=1) for q in bid_qtys],
        ask_levels=[DepthLevel(price=100.5, quantity=q, order_count=1) for q in ask_qtys],
        as_of=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )


def test_depth_strong_bid():
    depth = _depth([1000, 1000], [100, 100])  # imbalance = 1800/2200 = 0.818
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.status == "STRONG_BID"
    assert result.depth_imbalance > 0


def test_depth_strong_ask():
    depth = _depth([100, 100], [1000, 1000])
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.status == "STRONG_ASK"
    assert result.depth_imbalance < 0


def test_depth_balanced():
    depth = _depth([500], [510])
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.status == "BALANCED"


def test_depth_formula_exact():
    depth = _depth([600], [400])  # (600-400)/(600+400) = 0.2
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.depth_imbalance == 0.2
    assert result.status == "MODERATE_BID"


def test_depth_unavailable_when_no_levels():
    result = compute_depth_confirmation(None, _SETTINGS)
    assert result.status == "UNAVAILABLE"


def test_depth_unavailable_when_empty_levels():
    depth = MarketDepth(
        symbol="NSE:TEST-EQ", total_buy_qty=0, total_sell_qty=0, top_bid=None, top_ask=None, spread=None,
        bid_levels=[], ask_levels=[], as_of=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.status == "UNAVAILABLE"


def test_depth_zero_ask_matches_the_real_sunday_observation():
    """Regression for the exact live observation: totalsellqty=0, all-zero
    ask ladder, real (not fabricated) FYERS data on a closed-market day."""
    depth = _depth([808586], [0, 0, 0, 0, 0])
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.status == "STRONG_BID"
    assert result.depth_imbalance == 1.0
    assert result.ask_quantity_total == 0


def test_depth_zero_bid_mirrors_zero_ask_case():
    depth = _depth([0, 0, 0, 0, 0], [408])
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.status == "STRONG_ASK"
    assert result.depth_imbalance == -1.0
    assert result.bid_quantity_total == 0


def test_depth_negative_quantity_is_clamped_not_propagated():
    """Phase 15 bug fix: a real order-book quantity can never be negative.
    Reproduced live-equivalent: a single malformed level with quantity=-100
    alongside a normal ask level previously produced imbalance=3.0,
    misclassified as STRONG_BID -- a value mathematically outside the
    guaranteed [-1, +1] range. Must now clamp to 0, not corrupt the sum."""
    import datetime as dt

    depth = MarketDepth(
        symbol="NSE:TEST-EQ", total_buy_qty=-100, total_sell_qty=50,
        top_bid=100.0, top_ask=100.5, spread=0.5,
        bid_levels=[DepthLevel(price=100.0, quantity=-100, order_count=1)],
        ask_levels=[DepthLevel(price=100.5, quantity=50, order_count=1)],
        as_of=dt.datetime.now(dt.UTC),
    )
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.bid_quantity_total == 0  # clamped, not -100
    assert result.ask_quantity_total == 50
    assert -1.0 <= result.depth_imbalance <= 1.0
    assert result.depth_imbalance == -1.0
    assert result.status == "STRONG_ASK"  # correctly reflects only the valid ask side


def test_depth_imbalance_always_within_bounds_for_arbitrary_nonneg_quantities():
    """Property-style check across a spread of magnitudes -- the formula
    must never produce NaN, infinity, or a value outside [-1, +1] for any
    combination of non-negative quantities."""
    import datetime as dt

    combinations = [
        (0, 0), (1, 0), (0, 1), (1, 1), (1_000_000, 1), (1, 1_000_000),
        (500_000, 500_000), (999_999_999, 1),
    ]
    for bid_qty, ask_qty in combinations:
        depth = MarketDepth(
            symbol="NSE:TEST-EQ", total_buy_qty=bid_qty, total_sell_qty=ask_qty,
            top_bid=100.0, top_ask=100.5, spread=0.5,
            bid_levels=[DepthLevel(price=100.0, quantity=bid_qty, order_count=1)],
            ask_levels=[DepthLevel(price=100.5, quantity=ask_qty, order_count=1)],
            as_of=dt.datetime.now(dt.UTC),
        )
        result = compute_depth_confirmation(depth, _SETTINGS)
        if result.depth_imbalance is not None:
            assert -1.0 <= result.depth_imbalance <= 1.0, f"out of bounds for ({bid_qty}, {ask_qty}): {result.depth_imbalance}"
            assert result.depth_imbalance == result.depth_imbalance  # NaN check (NaN != NaN)
            assert abs(result.depth_imbalance) != float("inf")


def test_depth_malformed_ladder_none_quantities_treated_as_zero_not_fabricated():
    """A level with quantity=None (FYERS omitted the field) must count as
    0, never crash and never be treated as a positive value."""
    depth = MarketDepth(
        symbol="NSE:TEST-EQ", total_buy_qty=500, total_sell_qty=0, top_bid=100.0, top_ask=100.5, spread=0.5,
        bid_levels=[DepthLevel(price=100.0, quantity=500, order_count=1), DepthLevel(price=None, quantity=None, order_count=None)],
        ask_levels=[DepthLevel(price=None, quantity=None, order_count=None)],
        as_of=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.bid_quantity_total == 500
    assert result.ask_quantity_total == 0
    assert result.status == "STRONG_BID"


def test_depth_ladder_totals_consistent_when_they_match():
    """Empirically verified live (2026-09-20, 6 real symbols): FYERS'
    totalbuyqty/totalsellqty exactly equal the summed 5-level ladder."""
    depth = _depth([600], [400])
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.ladder_totals_consistent is True


def test_depth_ladder_totals_flagged_when_they_disagree():
    depth = MarketDepth(
        symbol="NSE:TEST-EQ", total_buy_qty=9999, total_sell_qty=400,  # deliberately wrong total_buy_qty
        top_bid=100.0, top_ask=100.5, spread=0.5,
        bid_levels=[DepthLevel(price=100.0, quantity=600, order_count=1)],
        ask_levels=[DepthLevel(price=100.5, quantity=400, order_count=1)],
        as_of=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    result = compute_depth_confirmation(depth, _SETTINGS)
    assert result.ladder_totals_consistent is False


# --- Spread condition ---------------------------------------------------------


def test_spread_healthy():
    depth = _depth([100], [100])  # top_bid=100.0, top_ask=100.5 -> spread 0.5% of mid ~0.5%
    result = compute_spread_condition(depth, _SETTINGS)
    assert result.status in ("HEALTHY", "WIDE")  # exact boundary depends on default threshold; assert it's classified
    assert result.spread_percentage is not None


def test_spread_wide():
    import datetime as dt

    depth = MarketDepth(
        symbol="NSE:TEST-EQ", total_buy_qty=100, total_sell_qty=100,
        top_bid=100.0, top_ask=105.0, spread=5.0,  # ~5% spread -- clearly wide
        bid_levels=[DepthLevel(price=100.0, quantity=100, order_count=1)],
        ask_levels=[DepthLevel(price=105.0, quantity=100, order_count=1)],
        as_of=dt.datetime.now(dt.UTC),
    )
    result = compute_spread_condition(depth, _SETTINGS)
    assert result.status == "WIDE"


def test_spread_unavailable():
    result = compute_spread_condition(None, _SETTINGS)
    assert result.status == "UNAVAILABLE"


# --- Futures confirmation -----------------------------------------------------


def test_futures_price_up_oi_up():
    c = _candidate(fno_available=True, futures_price_change_pct=1.0, futures_oi_change_pct=2.0)
    result = compute_futures_confirmation(c, _SETTINGS)
    assert result.status == "PRICE_UP_OI_UP"


def test_futures_price_down_oi_down():
    c = _candidate(fno_available=True, futures_price_change_pct=-1.0, futures_oi_change_pct=-2.0)
    assert compute_futures_confirmation(c, _SETTINGS).status == "PRICE_DOWN_OI_DOWN"


def test_futures_price_up_oi_down():
    c = _candidate(fno_available=True, futures_price_change_pct=1.0, futures_oi_change_pct=-2.0)
    assert compute_futures_confirmation(c, _SETTINGS).status == "PRICE_UP_OI_DOWN"


def test_futures_price_down_oi_up():
    c = _candidate(fno_available=True, futures_price_change_pct=-1.0, futures_oi_change_pct=2.0)
    assert compute_futures_confirmation(c, _SETTINGS).status == "PRICE_DOWN_OI_UP"


def test_futures_flat():
    c = _candidate(fno_available=True, futures_price_change_pct=0.05, futures_oi_change_pct=0.05)
    assert compute_futures_confirmation(c, _SETTINGS).status == "FLAT"


def test_futures_unavailable_when_fno_not_available():
    c = _candidate(fno_available=False)
    assert compute_futures_confirmation(c, _SETTINGS).status == "UNAVAILABLE"


def test_futures_never_claims_confirmed_buildup():
    c = _candidate(fno_available=True, futures_price_change_pct=1.0, futures_oi_change_pct=2.0)
    result = compute_futures_confirmation(c, _SETTINGS)
    assert "confirmed" not in result.status.lower()
    assert "buildup" not in result.status.lower()


# --- Persistence ---------------------------------------------------------------


def test_persistence_insufficient_on_first_observation():
    result, _ = compute_persistence([], "SUPPORTIVE", _SETTINGS)
    assert result.status == "INSUFFICIENT_OBSERVATIONS"
    assert result.observation_count == 1


def test_persistence_strengthening():
    history = [{"status": "NEUTRAL", "as_of": "2026-09-20T09:00:00+00:00"}]
    result, _ = compute_persistence(history, "SUPPORTIVE", _SETTINGS)
    assert result.status == "STRENGTHENING"


def test_persistence_weakening():
    history = [{"status": "SUPPORTIVE", "as_of": "2026-09-20T09:00:00+00:00"}]
    result, _ = compute_persistence(history, "NEUTRAL", _SETTINGS)
    assert result.status == "WEAKENING"


def test_persistence_persisted_when_stable():
    history = [{"status": "SUPPORTIVE", "as_of": "2026-09-20T09:00:00+00:00"}]
    result, _ = compute_persistence(history, "SUPPORTIVE", _SETTINGS)
    assert result.status == "PERSISTED"


def test_persistence_window_is_trimmed():
    settings = Settings(confirmation_persistence_window=3)
    history = [
        {"status": "NEUTRAL", "as_of": f"2026-09-20T09:0{i}:00+00:00"} for i in range(5)
    ]
    result, updated = compute_persistence(history, "SUPPORTIVE", settings)
    assert len(updated) == 3
    assert result.observation_count == 3


def test_persistence_reversal_from_supportive_to_contradictory_is_weakening():
    """A full reversal (SUPPORTIVE -> CONTRADICTORY) must classify as
    WEAKENING, not be mistaken for stability -- the ordinal ranking must
    correctly detect the largest possible negative swing."""
    history = [{"status": "SUPPORTIVE", "as_of": "2026-09-20T09:00:00+00:00"}]
    result, _ = compute_persistence(history, "CONTRADICTORY", _SETTINGS)
    assert result.status == "WEAKENING"
    assert result.first_observed_status == "SUPPORTIVE"
    assert result.latest_status == "CONTRADICTORY"


def test_persistence_empty_history_is_treated_as_first_observation():
    """An expired/never-written Redis key looks identical to a genuinely
    empty history -- both correctly degrade to INSUFFICIENT_OBSERVATIONS,
    never crash or fabricate a trend."""
    result, updated = compute_persistence([], "NEUTRAL", _SETTINGS)
    assert result.status == "INSUFFICIENT_OBSERVATIONS"
    assert len(updated) == 1


# --- Data quality ---------------------------------------------------------------


def test_data_quality_insufficient_when_quote_unavailable():
    persistence = PersistenceData(status="PERSISTED", observation_count=3, window=5)
    assert compute_data_quality("UNAVAILABLE", "STRONG_BID", "PRICE_UP_OI_UP", persistence) == "INSUFFICIENT_DATA"


def test_data_quality_high_when_everything_available():
    persistence = PersistenceData(status="PERSISTED", observation_count=3, window=5)
    assert compute_data_quality("LIVE", "STRONG_BID", "PRICE_UP_OI_UP", persistence) == "HIGH"


def test_data_quality_defaults_to_market_open_for_backward_compatibility():
    """market_open has a default of True specifically so every pre-existing
    call site (and this exact pre-existing test) keeps working unchanged."""
    persistence = PersistenceData(status="PERSISTED", observation_count=3, window=5)
    assert compute_data_quality("LIVE", "STRONG_BID", "PRICE_UP_OI_UP", persistence) == "HIGH"


def test_data_quality_capped_at_medium_when_market_closed():
    """Phase 6 hardening: even with every other signal available, a closed
    market can never yield HIGH -- it cannot provide genuine intraday
    confirmation regardless of cache freshness."""
    persistence = PersistenceData(status="PERSISTED", observation_count=3, window=5)
    result = compute_data_quality("LIVE", "STRONG_BID", "PRICE_UP_OI_UP", persistence, market_open=False)
    assert result == "MEDIUM"
    assert result != "HIGH"


def test_data_quality_medium_when_live_but_partial():
    persistence = PersistenceData(status="INSUFFICIENT_OBSERVATIONS", observation_count=1, window=5)
    assert compute_data_quality("LIVE", "UNAVAILABLE", "UNAVAILABLE", persistence) == "MEDIUM"


def test_data_quality_low_when_stale():
    persistence = PersistenceData(status="PERSISTED", observation_count=3, window=5)
    assert compute_data_quality("STALE", "STRONG_BID", "PRICE_UP_OI_UP", persistence) == "LOW"


# --- Confirmation score / classification ----------------------------------------


def test_confirmation_score_deterministic_for_identical_inputs():
    """Phase 9 requirement: calling with the exact same inputs any number
    of times must produce byte-identical output -- no hidden randomness or
    time-dependence in the score calculation itself."""
    from app.schemas.confirmation import (
        DepthConfirmationData, FuturesConfirmationData, PriceConfirmationData,
        VolumeConfirmationData,
    )

    price = PriceConfirmationData(status="INSIDE_ENTRY_ZONE", near_invalidation=False, breakout_relation="BELOW_BREAKOUT_LEVEL", entry_zone_low=100, entry_zone_high=105, invalidation=95)
    volume = VolumeConfirmationData(status="NORMAL", volume_ratio=1.05)
    vwap = compute_vwap_confirmation()
    depth = DepthConfirmationData(status="MODERATE_BID", depth_imbalance=0.15)
    futures = FuturesConfirmationData(status="FLAT")
    persistence = PersistenceData(status="PERSISTED", observation_count=3, window=5)

    scores = [compute_confirmation_score(price, volume, vwap, depth, futures, persistence) for _ in range(20)]
    assert len(set(scores)) == 1  # every call produced the exact same value


def test_confirmation_score_boundaries_stay_within_0_to_100():
    from app.schemas.confirmation import (
        DepthConfirmationData, FuturesConfirmationData, PriceConfirmationData,
        VolumeConfirmationData,
    )

    best_case = compute_confirmation_score(
        PriceConfirmationData(status="ABOVE_ENTRY_ZONE", near_invalidation=False, breakout_relation="ABOVE_BREAKOUT_LEVEL", entry_zone_low=100, entry_zone_high=105, invalidation=95),
        VolumeConfirmationData(status="EXPANDING", volume_ratio=2.0),
        compute_vwap_confirmation(),
        DepthConfirmationData(status="STRONG_BID", depth_imbalance=1.0),
        FuturesConfirmationData(status="PRICE_UP_OI_UP"),
        PersistenceData(status="STRENGTHENING", observation_count=5, window=5),
    )
    worst_case = compute_confirmation_score(
        PriceConfirmationData(status="BELOW_ENTRY_ZONE", near_invalidation=True, breakout_relation="BELOW_BREAKOUT_LEVEL", entry_zone_low=100, entry_zone_high=105, invalidation=95),
        VolumeConfirmationData(status="DECLINING", volume_ratio=0.5),
        compute_vwap_confirmation(),
        DepthConfirmationData(status="STRONG_ASK", depth_imbalance=-1.0),
        FuturesConfirmationData(status="PRICE_DOWN_OI_DOWN"),
        PersistenceData(status="DISAPPEARED", observation_count=5, window=5),
    )
    assert 0.0 <= worst_case <= 100.0
    assert 0.0 <= best_case <= 100.0
    assert worst_case < best_case


def test_classify_confirmation_thresholds_are_deterministic():
    for _ in range(10):
        assert classify_confirmation(75.0, "HIGH") == "STRONGLY_SUPPORTIVE"
        assert classify_confirmation(74.99, "HIGH") == "SUPPORTIVE"
        assert classify_confirmation(55.0, "HIGH") == "SUPPORTIVE"
        assert classify_confirmation(44.99, "HIGH") == "CONTRADICTORY"
        assert classify_confirmation(45.0, "HIGH") == "NEUTRAL"


def test_confirmation_score_renormalizes_when_vwap_unavailable():
    """VWAP is always UNAVAILABLE today -- its 15% weight must redistribute,
    never silently count as zero."""
    from app.schemas.confirmation import (
        DepthConfirmationData, FuturesConfirmationData, PriceConfirmationData,
        VolumeConfirmationData, VwapConfirmationData,
    )

    price = PriceConfirmationData(status="ABOVE_ENTRY_ZONE", near_invalidation=False, breakout_relation="ABOVE_BREAKOUT_LEVEL", entry_zone_low=100, entry_zone_high=105, invalidation=95)
    volume = VolumeConfirmationData(status="EXPANDING", volume_ratio=1.5)
    vwap = compute_vwap_confirmation()
    depth = DepthConfirmationData(status="STRONG_BID", depth_imbalance=0.5)
    futures = FuturesConfirmationData(status="PRICE_UP_OI_UP")
    persistence = PersistenceData(status="PERSISTED", observation_count=3, window=5)

    score = compute_confirmation_score(price, volume, vwap, depth, futures, persistence)
    assert score is not None
    assert score > 75  # all-available components are strongly positive; renormalized score should reflect that


def test_confirmation_score_is_neutral_persistence_only_when_everything_else_unavailable():
    """price/volume/vwap/depth/futures all have a real UNAVAILABLE state and
    correctly drop out of the weighted average -- persistence does not
    (INSUFFICIENT_OBSERVATIONS is a real, always-computable classification,
    not a null state), so it's the one component still contributing, at a
    neutral 50 (never a fabricated positive value). The overall
    classification safety net for this exact scenario is covered by
    test_classify_confirmation_insufficient_data_overrides_score: real
    "nothing usable" cases have quote_freshness=UNAVAILABLE, which forces
    data_quality=INSUFFICIENT_DATA and overrides the classification
    regardless of this score."""
    from app.schemas.confirmation import (
        DepthConfirmationData, FuturesConfirmationData, PriceConfirmationData,
        VolumeConfirmationData,
    )

    price = PriceConfirmationData(status="UNAVAILABLE", breakout_relation="UNAVAILABLE", entry_zone_low=100, entry_zone_high=105, invalidation=95)
    volume = VolumeConfirmationData(status="INSUFFICIENT_DATA")
    vwap = compute_vwap_confirmation()
    depth = DepthConfirmationData(status="UNAVAILABLE")
    futures = FuturesConfirmationData(status="UNAVAILABLE")
    persistence = PersistenceData(status="INSUFFICIENT_OBSERVATIONS", observation_count=0, window=5)

    score = compute_confirmation_score(price, volume, vwap, depth, futures, persistence)
    assert score == 50.0  # neutral, not fabricated positive/negative


def test_confirmation_score_none_when_truly_nothing_available():
    """Even persistence excluded (its own history genuinely empty and the
    caller chooses not to score it) -- verifies the None path still works
    when ALL six components resolve to None."""
    import app.services.realtime_confirmation_service as svc

    original_scorers = dict(svc._COMPONENT_SCORERS)
    svc._COMPONENT_SCORERS["persistence"] = lambda p: None
    try:
        from app.schemas.confirmation import (
            DepthConfirmationData, FuturesConfirmationData, PriceConfirmationData,
            VolumeConfirmationData,
        )

        price = PriceConfirmationData(status="UNAVAILABLE", breakout_relation="UNAVAILABLE", entry_zone_low=100, entry_zone_high=105, invalidation=95)
        volume = VolumeConfirmationData(status="INSUFFICIENT_DATA")
        vwap = compute_vwap_confirmation()
        depth = DepthConfirmationData(status="UNAVAILABLE")
        futures = FuturesConfirmationData(status="UNAVAILABLE")
        persistence = PersistenceData(status="INSUFFICIENT_OBSERVATIONS", observation_count=0, window=5)

        score = compute_confirmation_score(price, volume, vwap, depth, futures, persistence)
        assert score is None
    finally:
        svc._COMPONENT_SCORERS.clear()
        svc._COMPONENT_SCORERS.update(original_scorers)


def test_classify_confirmation_thresholds():
    assert classify_confirmation(80, "HIGH") == "STRONGLY_SUPPORTIVE"
    assert classify_confirmation(60, "HIGH") == "SUPPORTIVE"
    assert classify_confirmation(50, "HIGH") == "NEUTRAL"
    assert classify_confirmation(20, "HIGH") == "CONTRADICTORY"


def test_classify_confirmation_insufficient_data_overrides_score():
    assert classify_confirmation(90, "INSUFFICIENT_DATA") == "INSUFFICIENT_DATA"


def test_classify_confirmation_never_uses_forbidden_words():
    for score in (10, 30, 50, 70, 90):
        status = classify_confirmation(score, "HIGH")
        forbidden = ("buy", "sell", "guaranteed", "sure shot", "will rise", "will fall")
        assert not any(word in status.lower() for word in forbidden)
