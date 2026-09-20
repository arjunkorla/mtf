"""Unit tests for ScannerRunRequest.symbols (Phase 3: controlled scanner
size) -- validated at the schema layer so an unconfigured/malformed symbol
never reaches FYERS or the DB."""

import pytest
from pydantic import ValidationError

from app.schemas.scanner import ScannerRunRequest

_BASE = {"available_capital": 100000, "risk_percent": 2, "max_positions": 5, "holding_period": "1-4 weeks"}


def test_symbols_omitted_defaults_to_none():
    req = ScannerRunRequest(**_BASE)
    assert req.symbols is None


def test_symbols_valid_subset_is_accepted():
    req = ScannerRunRequest(**_BASE, symbols=["NSE:RELIANCE-EQ", "NSE:INFY-EQ"])
    assert req.symbols == ["NSE:RELIANCE-EQ", "NSE:INFY-EQ"]


def test_symbols_duplicates_are_deduplicated_preserving_order():
    req = ScannerRunRequest(**_BASE, symbols=["NSE:RELIANCE-EQ", "NSE:INFY-EQ", "NSE:RELIANCE-EQ"])
    assert req.symbols == ["NSE:RELIANCE-EQ", "NSE:INFY-EQ"]


def test_symbols_empty_list_is_rejected():
    with pytest.raises(ValidationError, match="empty list"):
        ScannerRunRequest(**_BASE, symbols=[])


def test_symbols_unknown_symbol_is_rejected():
    with pytest.raises(ValidationError, match="unknown symbol"):
        ScannerRunRequest(**_BASE, symbols=["NSE:NOTAREALSTOCK-EQ"])
