import pytest

pytestmark = pytest.mark.asyncio


async def test_health_endpoint(app_client):
    resp = await app_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("ok", "degraded")
    names = {c["name"] for c in body["components"]}
    assert {"database", "redis", "fyers"} <= names
