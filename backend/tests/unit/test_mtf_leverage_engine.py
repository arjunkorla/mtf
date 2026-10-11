from app.core.constants import MtfLeverageStatus
from app.engines.mtf_leverage_engine import compute_mtf_leverage


def test_not_mtf_eligible_short_circuits():
    result = compute_mtf_leverage(symbol_is_mtf_eligible=False, required_margin_pct=20.0)
    assert result.mtf_status == MtfLeverageStatus.NOT_MTF_ELIGIBLE.value
    assert result.effective_leverage is None


def test_unverified_when_margin_data_missing():
    result = compute_mtf_leverage(symbol_is_mtf_eligible=True, required_margin_pct=None)
    assert result.mtf_status == MtfLeverageStatus.UNVERIFIED.value
    assert result.effective_leverage is None
    assert result.reason_unverified is not None


def test_verified_leverage_computed_correctly():
    result = compute_mtf_leverage(symbol_is_mtf_eligible=True, required_margin_pct=25.0)
    assert result.mtf_status == MtfLeverageStatus.VERIFIED.value
    assert result.effective_leverage == 4.0
    assert result.required_margin_pct == 25.0
    assert len(result.evidence) == 1


def test_leverage_below_3x_still_verified_but_flagged_negative():
    result = compute_mtf_leverage(symbol_is_mtf_eligible=True, required_margin_pct=40.0)
    assert result.mtf_status == MtfLeverageStatus.VERIFIED.value
    assert result.effective_leverage == 2.5
    assert result.evidence[0].is_positive is False


def test_malformed_margin_pct_is_treated_as_unverified():
    for bad_value in (0, -5.0, 150.0):
        result = compute_mtf_leverage(symbol_is_mtf_eligible=True, required_margin_pct=bad_value)
        assert result.mtf_status == MtfLeverageStatus.UNVERIFIED.value
        assert result.effective_leverage is None


def test_never_defaults_to_a_guessed_leverage():
    """Regression test for AGENTS.md's 'never assume leverage': every
    non-VERIFIED status must carry effective_leverage=None."""
    cases = [
        compute_mtf_leverage(symbol_is_mtf_eligible=False, required_margin_pct=None),
        compute_mtf_leverage(symbol_is_mtf_eligible=False, required_margin_pct=10.0),
        compute_mtf_leverage(symbol_is_mtf_eligible=True, required_margin_pct=None),
        compute_mtf_leverage(symbol_is_mtf_eligible=True, required_margin_pct=-1.0),
    ]
    for result in cases:
        assert result.mtf_status != MtfLeverageStatus.VERIFIED.value
        assert result.effective_leverage is None
