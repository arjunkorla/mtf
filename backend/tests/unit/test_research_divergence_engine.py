from app.engines.research_divergence_engine import (
    ALIGNED_STRONG,
    ALIGNED_WEAK,
    INSUFFICIENT_DATA,
    MAJOR_DIVERGENCE,
    RESEARCH_DOWNGRADE,
    RESEARCH_UPGRADE,
    classify_divergence,
)


def test_insufficient_data_when_research_score_missing():
    delta, rank_delta, classification = classify_divergence(50.0, 3, None, None)
    assert classification == INSUFFICIENT_DATA
    assert delta is None and rank_delta is None


def test_aligned_strong_when_both_high_and_close():
    delta, rank_delta, classification = classify_divergence(75.0, 1, 78.0, 1)
    assert classification == ALIGNED_STRONG
    assert delta == 3.0
    assert rank_delta == 0


def test_aligned_weak_when_both_low_and_close():
    _, _, classification = classify_divergence(25.0, 8, 28.0, 8)
    assert classification == ALIGNED_WEAK


def test_research_upgrade_on_moderate_positive_gap():
    _, _, classification = classify_divergence(40.0, 5, 51.0, 4)
    assert classification == RESEARCH_UPGRADE


def test_research_downgrade_on_moderate_negative_gap():
    _, _, classification = classify_divergence(60.0, 2, 48.0, 4)
    assert classification == RESEARCH_DOWNGRADE


def test_major_divergence_on_the_phase5_reliance_numbers():
    """The actual Phase 5 finding: RELIANCE mtf_score=31.92 rank=6,
    research_confirmation_score=37.85 rank=3 -- a 3-rank jump, which this
    engine's MAJOR_RANK_GAP=3 is explicitly tuned to classify as
    MAJOR_DIVERGENCE, not a plain upgrade."""
    delta, rank_delta, classification = classify_divergence(31.92, 6, 37.85, 3)
    assert classification == MAJOR_DIVERGENCE
    assert rank_delta == -3
    assert round(delta, 2) == round(37.85 - 31.92, 2)


def test_major_divergence_by_score_gap_alone_even_without_rank_data():
    _, rank_delta, classification = classify_divergence(20.0, None, 55.0, None)
    assert classification == MAJOR_DIVERGENCE
    assert rank_delta is None


def test_never_a_trading_signal_only_diagnostic_labels():
    valid_labels = {ALIGNED_STRONG, ALIGNED_WEAK, RESEARCH_UPGRADE, RESEARCH_DOWNGRADE, MAJOR_DIVERGENCE, INSUFFICIENT_DATA}
    for mtf, research in [(10, 90), (90, 10), (50, 50), (0, 100)]:
        _, _, classification = classify_divergence(mtf, 1, research, 1)
        assert classification in valid_labels
