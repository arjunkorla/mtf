from app.engines.sector_participation_engine import (
    DIVERGING,
    INSUFFICIENT_DATA,
    LAGGING_SECTOR,
    LEADING_SECTOR,
    PARTICIPATING,
    classify_sector_participation,
    classify_sector_participation_from_deltas,
)


def test_insufficient_data_when_returns_missing():
    state, evidence = classify_sector_participation(None, None, "UPTREND")
    assert state == INSUFFICIENT_DATA
    assert evidence == []


def test_leading_sector_when_outperforming_and_uptrending():
    state, _ = classify_sector_participation(stock_return_20d=10.0, sector_return_20d=4.0, trend_structure="STRONG_UPTREND")
    assert state == LEADING_SECTOR


def test_diverging_matches_the_phase5_reliance_case():
    """RELIANCE, Phase 5: stock underperformed its own STRONG sector by
    ~-4.56% over 20D while in a STRONG_DOWNTREND -- exactly the case this
    classification exists to catch."""
    state, evidence = classify_sector_participation(stock_return_20d=-2.268, sector_return_20d=2.292, trend_structure="STRONG_DOWNTREND")
    assert state == DIVERGING
    assert evidence[0].value < 0


def test_lagging_sector_when_underperforming_without_hard_downtrend():
    state, _ = classify_sector_participation(stock_return_20d=-1.0, sector_return_20d=5.0, trend_structure="RANGE_BOUND")
    assert state == LAGGING_SECTOR


def test_participating_when_roughly_matching_sector():
    state, _ = classify_sector_participation(stock_return_20d=5.0, sector_return_20d=4.5, trend_structure="UPTREND")
    assert state == PARTICIPATING


def test_5d_evidence_included_when_provided():
    _, evidence = classify_sector_participation(10.0, 4.0, "UPTREND", stock_return_5d=2.0, sector_return_5d=1.0)
    assert len(evidence) == 2
    assert "5D" in evidence[1].label


def test_from_deltas_variant_matches_raw_variant_classification():
    raw_state, _ = classify_sector_participation(stock_return_20d=-2.268, sector_return_20d=2.292, trend_structure="STRONG_DOWNTREND")
    delta_state, evidence = classify_sector_participation_from_deltas(vs_sector_pct_20d=-4.56, trend_structure="STRONG_DOWNTREND")
    assert raw_state == delta_state == DIVERGING
    assert evidence[0].value == -4.56


def test_from_deltas_insufficient_data_when_none():
    state, evidence = classify_sector_participation_from_deltas(None, "UPTREND")
    assert state == INSUFFICIENT_DATA
    assert evidence == []
