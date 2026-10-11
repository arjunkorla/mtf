"""Tests for app.integrations.fyers.margin -- runs in USE_MOCK_FYERS=true
mode (module-level fixture in conftest.py)."""

import pytest

from app.config import Settings
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.margin import extract_required_margin_pct, get_symbol_margin


def _mock_client() -> FyersClient:
    return FyersClient(settings=Settings(use_mock_fyers=True))


@pytest.mark.asyncio
async def test_get_symbol_margin_returns_mock_shape_in_mock_mode():
    client = _mock_client()
    response = await get_symbol_margin(client, "NSE:RELIANCE-EQ", ltp=2951.2)
    assert response is not None
    assert response["s"] == "ok"
    assert "margin_total" in response["data"]


@pytest.mark.asyncio
async def test_get_symbol_margin_returns_none_without_ltp():
    client = _mock_client()
    assert await get_symbol_margin(client, "NSE:RELIANCE-EQ", ltp=None) is None
    assert await get_symbol_margin(client, "NSE:RELIANCE-EQ", ltp=0) is None


def test_extract_required_margin_pct_round_trips_mock_response():
    from app.integrations.fyers.mock_responses import mock_margin_response

    response = mock_margin_response("NSE:RELIANCE-EQ", required_margin_pct=25.0, ltp=2951.2)
    pct = extract_required_margin_pct(response, ltp=2951.2)
    assert pct is not None
    assert abs(pct - 25.0) < 0.01


def test_extract_required_margin_pct_none_on_missing_data():
    assert extract_required_margin_pct(None, ltp=2951.2) is None
    assert extract_required_margin_pct({"s": "ok"}, ltp=2951.2) is None
    assert extract_required_margin_pct({"s": "ok", "data": {}}, ltp=2951.2) is None


def test_extract_required_margin_pct_none_on_implausible_value():
    assert extract_required_margin_pct({"s": "ok", "data": {"margin_total": 999999}}, ltp=100.0) is None
