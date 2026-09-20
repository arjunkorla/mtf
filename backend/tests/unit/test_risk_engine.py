import pytest

from app.engines.risk_engine import InvalidRiskInputError, compute_position_size


def test_basic_position_sizing_matches_formula():
    sizing = compute_position_size(
        available_capital=100_000,
        risk_percent=2,
        entry_price=100,
        invalidation_price=95,
    )
    # max_risk = 100000 * 0.02 = 2000; risk_per_share = 5; quantity = 400
    assert sizing.max_rupee_risk == 2000.0
    assert sizing.risk_per_share == 5.0
    assert sizing.quantity == 400
    assert sizing.capital_required == 40_000.0


def test_quantity_capped_by_available_capital():
    sizing = compute_position_size(
        available_capital=1_000,
        risk_percent=90,
        entry_price=10,
        invalidation_price=9,  # tight stop -> risk-based quantity far exceeds what capital allows
    )
    assert sizing.capital_required <= 1_000
    assert any("capped by available capital" in n for n in sizing.notes)


def test_max_position_pct_cap_applied():
    sizing = compute_position_size(
        available_capital=100_000,
        risk_percent=10,
        entry_price=100,
        invalidation_price=95,
        max_position_pct_of_capital=10,
    )
    assert sizing.capital_required <= 10_000


def test_invalidation_must_be_below_entry():
    with pytest.raises(InvalidRiskInputError):
        compute_position_size(
            available_capital=100_000, risk_percent=2, entry_price=100, invalidation_price=100,
        )


def test_zero_quantity_when_risk_too_small():
    sizing = compute_position_size(
        available_capital=100_000, risk_percent=0.001, entry_price=1000, invalidation_price=900,
    )
    assert sizing.quantity == 0
    assert any("too small" in n for n in sizing.notes)
