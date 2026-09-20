"""Tests for app.data.fo_symbol_master_parser (Phase 1 F&O investigation).

Uses real captured NSE_FO.csv rows (RELIANCE's Sep/Oct/Nov 2026 contracts,
live-verified 2026-09-20) rather than synthetic data, so the parser is
proven against the actual column layout, not an assumed one.
"""

import datetime as dt

from app.data.fo_symbol_master_parser import find_near_month_contract, parse_fo_symbol_master_csv
from app.integrations.fyers.fo_symbol_master import _MOCK_CSV

_OPTION_ROW = "101126092947566,RELIANCE26SEP620CE,12,500,0.05,,0915-1540|1815-1915:,2026-09-18,1790676600,NSE:RELIANCE26SEP620CE,10,11,92947566,RELIANCE,2885,-1.0,XX,101126092947566,None,0,0.0"
_NO_EXPIRY_ROW = "10100000002885,RELIANCE INDUSTRIES LTD,0,1,0.05,INE002A01018,0915-1530|1815-1915:,2026-09-18,,NSE:RELIANCE-EQ,10,10,2885,RELIANCE,2885,-1.0,XX,10100000002885,None,1,3.3"


def test_parses_real_captured_futures_rows():
    futures = parse_fo_symbol_master_csv(_MOCK_CSV)
    symbols = {f.symbol for f in futures}
    assert symbols == {"NSE:RELIANCE26SEPFUT", "NSE:RELIANCE26OCTFUT", "NSE:RELIANCE26NOVFUT"}
    assert all(f.underlying_ticker == "RELIANCE" for f in futures)


def test_option_rows_are_excluded_not_treated_as_futures():
    futures = parse_fo_symbol_master_csv(_OPTION_ROW)
    assert futures == []


def test_equity_rows_without_expiry_are_excluded():
    futures = parse_fo_symbol_master_csv(_NO_EXPIRY_ROW)
    assert futures == []


def test_find_near_month_contract_picks_soonest_unexpired():
    futures = parse_fo_symbol_master_csv(_MOCK_CSV)
    contract = find_near_month_contract(futures, "RELIANCE", as_of=dt.date(2026, 9, 20))
    assert contract is not None
    assert contract.symbol == "NSE:RELIANCE26SEPFUT"


def test_find_near_month_contract_skips_expired_contracts():
    futures = parse_fo_symbol_master_csv(_MOCK_CSV)
    # as_of after the Sep contract's expiry -> Oct becomes near-month
    contract = find_near_month_contract(futures, "RELIANCE", as_of=dt.date(2026, 10, 1))
    assert contract is not None
    assert contract.symbol == "NSE:RELIANCE26OCTFUT"


def test_find_near_month_contract_returns_none_for_unknown_ticker():
    futures = parse_fo_symbol_master_csv(_MOCK_CSV)
    assert find_near_month_contract(futures, "NOTAREALTICKER") is None


def test_find_near_month_contract_returns_none_when_all_expired():
    futures = parse_fo_symbol_master_csv(_MOCK_CSV)
    assert find_near_month_contract(futures, "RELIANCE", as_of=dt.date(2027, 1, 1)) is None
