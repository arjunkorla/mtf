import pytest

from app.services.live_data_hub import normalize_tick


def test_normalize_tick_mock_shape():
    tick = normalize_tick({"symbol": "NSE:RELIANCE-EQ", "ltp": 2950.5, "vol_traded_today": 12345, "timestamp": "2026-09-19T10:00:00+00:00"})
    assert tick == {
        "symbol": "NSE:RELIANCE-EQ",
        "ltp": 2950.5,
        "volume": 12345,
        "as_of": "2026-09-19T10:00:00+00:00",
    }


def test_normalize_tick_only_confirmed_fields_required():
    """symbol/ltp are the only confirmed live-tick fields (see
    websocket.py's module docstring) -- everything else must be optional."""
    tick = normalize_tick({"symbol": "NSE:TCS-EQ", "ltp": "4120.0"})
    assert tick["symbol"] == "NSE:TCS-EQ"
    assert tick["ltp"] == 4120.0
    assert tick["volume"] is None
    assert tick["as_of"]  # falls back to a generated timestamp, never missing


def test_normalize_tick_missing_symbol_raises():
    with pytest.raises(KeyError):
        normalize_tick({"ltp": 100})
