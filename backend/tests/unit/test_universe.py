"""Regression test for the Phase 2 investigation: NSE:TATAMOTORS-EQ was
confirmed live-invalid at FYERS (HTTP 422 "Invalid symbol provided") because
Tata Motors demerged into two separately-listed companies. Verified against
the real NSE_CM.csv symbol master on 2026-09-20: NSE:TMCV-EQ (commercial
vehicles, not yet F&O-eligible) and NSE:TMPV-EQ (passenger vehicles, has
active futures contracts) are the current valid successors."""

from app.data.universe import get_seed_universe


def test_obsolete_tatamotors_symbol_is_not_in_universe():
    symbols = {entry.symbol for entry in get_seed_universe()}
    assert "NSE:TATAMOTORS-EQ" not in symbols


def test_tata_motors_successor_symbols_are_present_with_verified_fno_flags():
    by_symbol = {entry.symbol: entry for entry in get_seed_universe()}

    assert "NSE:TMCV-EQ" in by_symbol
    assert by_symbol["NSE:TMCV-EQ"].is_fno is False  # verified: no NSE_FO.csv futures rows yet

    assert "NSE:TMPV-EQ" in by_symbol
    assert by_symbol["NSE:TMPV-EQ"].is_fno is True  # verified: TMPV26SEPFUT/OCTFUT/NOVFUT exist

    assert by_symbol["NSE:TMCV-EQ"].is_mtf_eligible is True
    assert by_symbol["NSE:TMPV-EQ"].is_mtf_eligible is True
