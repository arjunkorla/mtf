import pytest

from app.services.delivery_service import get_delivery_metrics

pytestmark = pytest.mark.asyncio


async def test_get_delivery_metrics_for_known_symbol():
    metrics = await get_delivery_metrics("RELIANCE")
    assert metrics is not None
    assert metrics.symbol == "RELIANCE"
    assert metrics.delivery_percentage == 77.01


async def test_get_delivery_metrics_for_unknown_symbol_returns_none():
    metrics = await get_delivery_metrics("NOTASTOCK")
    assert metrics is None
