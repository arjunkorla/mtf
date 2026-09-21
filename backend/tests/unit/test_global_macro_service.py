"""Tests for app.services.global_macro_service (Phase 11 research layer).
Runs in USE_MOCK_FYERS=true mode, exercising the real service code path
against the mock Yahoo Finance chart responses, not synthetic stand-ins for
the service itself.
"""

import pytest

from app.config import Settings
from app.integrations.global_macro.yahoo_finance_client import MACRO_SYMBOLS
from app.services.global_macro_service import get_global_macro_snapshot

pytestmark = pytest.mark.asyncio


async def test_get_global_macro_snapshot_returns_all_configured_symbols_in_mock_mode():
    quotes = await get_global_macro_snapshot(Settings(use_mock_fyers=True))
    assert len(quotes) == len(MACRO_SYMBOLS)
    labels = {q.label for q in quotes}
    assert labels == set(MACRO_SYMBOLS)


async def test_get_global_macro_snapshot_never_fabricates_missing_symbols(monkeypatch):
    """One symbol's fetch failing must not take down the rest, and must not
    be silently replaced with a fabricated value -- it's simply absent."""
    import app.services.global_macro_service as global_macro_service

    async def _flaky_fetch(ticker, settings):
        if ticker == "^GSPC":
            raise RuntimeError("simulated upstream outage")
        return {"chart": {"result": [{"meta": {"symbol": ticker, "regularMarketPrice": 1.0}}]}}

    monkeypatch.setattr(global_macro_service, "fetch_macro_chart", _flaky_fetch)

    quotes = await get_global_macro_snapshot(Settings(use_mock_fyers=False))
    labels = {q.label for q in quotes}
    assert "S&P 500" not in labels
    assert len(quotes) == len(MACRO_SYMBOLS) - 1
