"""Tests for app.data.sector_index_map (Phase 5 investigation).

Guards two things: the newly-added Consumer Durables mapping stays correct,
and the sectors confirmed to have no real standalone NSE index (verified
live against FYERS' full index list, 2026-09-20) never silently gain a
fabricated mapping later.
"""

from app.data.sector_index_map import get_sector_index_symbol


def test_previously_working_sectors_are_unaffected():
    assert get_sector_index_symbol("IT") == "NSE:NIFTYIT-INDEX"
    assert get_sector_index_symbol("Auto") == "NSE:NIFTYAUTO-INDEX"
    assert get_sector_index_symbol("Energy") == "NSE:NIFTYENERGY-INDEX"
    assert get_sector_index_symbol("Power") == "NSE:NIFTYENERGY-INDEX"


def test_consumer_durables_maps_to_the_real_verified_symbol():
    assert get_sector_index_symbol("Consumer Durables") == "NSE:NIFTYCONSRDURBL-INDEX"


def test_sectors_with_no_confirmed_standalone_index_stay_unavailable():
    """Must never silently gain a fabricated/guessed mapping -- missing
    sector data has to remain explicitly unavailable, never a positive
    score built on an invented index."""
    for sector in ("Telecom", "Cement", "Diversified", "Industrials"):
        assert get_sector_index_symbol(sector) is None


def test_unknown_sector_returns_none():
    assert get_sector_index_symbol("NotARealSector") is None


def test_none_sector_returns_none():
    assert get_sector_index_symbol(None) is None
