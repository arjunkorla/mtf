from app.engines.india_vix_engine import classify_vix_regime


def test_none_yields_insufficient_data():
    assert classify_vix_regime(None) == "INSUFFICIENT_DATA"


def test_below_low_threshold_is_low_volatility():
    assert classify_vix_regime(11.47) == "LOW_VOLATILITY"


def test_between_low_and_elevated_is_normal():
    assert classify_vix_regime(15.0) == "NORMAL"


def test_between_elevated_and_high_is_elevated():
    assert classify_vix_regime(25.0) == "ELEVATED"


def test_at_or_above_high_threshold_is_high():
    assert classify_vix_regime(31.0) == "HIGH"


def test_boundaries_are_inclusive_on_the_lower_band():
    assert classify_vix_regime(12.0) == "NORMAL"  # not LOW_VOLATILITY at exactly the threshold
    assert classify_vix_regime(20.0) == "ELEVATED"
    assert classify_vix_regime(30.0) == "HIGH"
