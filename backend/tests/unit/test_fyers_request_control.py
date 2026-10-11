"""Phase 0: process-wide FYERS rate limiter + request metering.

Runs against the isolated test Redis DB (15, see conftest.py) -- the same
Lua script production uses -- with an injected clock so window behavior is
deterministic. Never touches the real FYERS session: settings carry a fake
token and every HTTP call goes through httpx.MockTransport.
"""

import asyncio
import json

import httpx
import pytest

from app.config import Settings
from app.core.exceptions import FyersLocalCapacityExceeded, FyersRateLimitError
from app.integrations.fyers import request_control
from app.integrations.fyers.fyers_client import FyersClient
from app.integrations.fyers.request_control import (
    ADMITTED,
    COOLDOWN,
    DAY_EXHAUSTED,
    WAIT_WINDOW,
    FyersRateLimiter,
    RequestPriority,
    fyers_priority,
    tier_limits,
    usage_snapshot,
)

FAKE_TOKEN = "test-token-never-real"


def _settings(**overrides) -> Settings:
    base = dict(
        use_mock_fyers=False, fyers_client_id="test-client", fyers_access_token=FAKE_TOKEN,
        fyers_limit_per_second=8, fyers_limit_per_minute=160, fyers_limit_per_day=80_000,
        fyers_429_cooldown_seconds=5.0,
    )
    base.update(overrides)
    return Settings(**base)


class _Clock:
    def __init__(self, start_ms: float = 1_000_000_000_000.0):
        self.now = start_ms

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(request_control, "_limiter", FyersRateLimiter(clock_ms=c))
    return c


@pytest.fixture(autouse=True)
def _reset_limiter(monkeypatch):
    monkeypatch.setattr(request_control, "_limiter", None)


def _ok_client(settings: Settings, calls: dict, status: int = 200, body: dict | None = None, priority=None) -> FyersClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] = calls.get("n", 0) + 1
        calls.setdefault("headers", []).append(dict(request.headers))
        return httpx.Response(status, json=body if body is not None else {"s": "ok", "d": []})

    client = FyersClient(settings=settings, priority=priority)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


# ---- tier configuration ----------------------------------------------------


def test_safety_ceilings_stay_below_provider_limits():
    s = Settings()
    assert s.fyers_limit_per_second < request_control.PROVIDER_LIMIT_PER_SECOND
    assert s.fyers_limit_per_minute < request_control.PROVIDER_LIMIT_PER_MINUTE
    assert s.fyers_limit_per_day < request_control.PROVIDER_LIMIT_PER_DAY


def test_lower_tiers_get_strictly_smaller_budgets():
    s = _settings()
    crit = tier_limits(s, RequestPriority.CRITICAL)
    inter = tier_limits(s, RequestPriority.INTERACTIVE)
    bg = tier_limits(s, RequestPriority.BACKGROUND)
    enr = tier_limits(s, RequestPriority.ENRICHMENT)
    assert crit[0] >= inter[0] > bg[0] > enr[0]
    assert crit[1] > inter[1] > bg[1] > enr[1]


# ---- per-second / per-minute control ------------------------------------------


@pytest.mark.asyncio
async def test_per_second_ceiling_enforced(clock):
    s = _settings()
    limiter = request_control.get_rate_limiter()
    lim_s, _, _ = tier_limits(s, RequestPriority.INTERACTIVE)

    results = [await limiter._admit(s, RequestPriority.INTERACTIVE, force=False) for _ in range(lim_s + 1)]
    assert [code for _, code in results[:lim_s]] == [ADMITTED] * lim_s
    wait_ms, code = results[-1]
    assert code == WAIT_WINDOW
    assert 0 < wait_ms <= 1000

    clock.now += 1001  # window slides
    assert (await limiter._admit(s, RequestPriority.INTERACTIVE, force=False))[1] == ADMITTED


@pytest.mark.asyncio
async def test_per_minute_ceiling_enforced(clock):
    s = _settings()
    limiter = request_control.get_rate_limiter()
    lim_s, lim_m, _ = tier_limits(s, RequestPriority.INTERACTIVE)

    admitted = 0
    start = clock.now
    while admitted < lim_m:
        for _ in range(lim_s):
            if admitted == lim_m:
                break
            _, code = await limiter._admit(s, RequestPriority.INTERACTIVE, force=False)
            assert code == ADMITTED
            admitted += 1
        clock.now += 1001  # stay under per-second, keep filling the minute
    assert clock.now - start < 60_000  # all of it happened inside one minute

    wait_ms, code = await limiter._admit(s, RequestPriority.INTERACTIVE, force=False)
    assert code == WAIT_WINDOW
    assert wait_ms > 1000  # blocked by the MINUTE window, not the second one

    clock.now = start + 60_001
    assert (await limiter._admit(s, RequestPriority.INTERACTIVE, force=False))[1] == ADMITTED


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_budget(clock):
    """The bug Phase 0 fixes: budgets were per FyersClient instance."""
    s = _settings()
    limiter = request_control.get_rate_limiter()
    lim_s, _, _ = tier_limits(s, RequestPriority.CRITICAL)

    results = await asyncio.gather(*[limiter._admit(s, RequestPriority.CRITICAL, force=False) for _ in range(25)])
    assert sum(1 for _, code in results if code == ADMITTED) == lim_s


@pytest.mark.asyncio
async def test_separate_limiter_instances_share_redis_budget(clock):
    """Two limiter objects (as two processes would have) coordinate through
    Redis -- neither gets its own private budget."""
    s = _settings()
    a = FyersRateLimiter(clock_ms=clock)
    b = FyersRateLimiter(clock_ms=clock)
    lim_s, _, _ = tier_limits(s, RequestPriority.CRITICAL)

    codes = []
    for i in range(lim_s + 4):
        _, code = await (a if i % 2 else b)._admit(s, RequestPriority.CRITICAL, force=False)
        codes.append(code)
    assert codes.count(ADMITTED) == lim_s
    assert a.backend == b.backend == "redis"


@pytest.mark.asyncio
async def test_concurrent_fyers_clients_are_throttled_together(clock, monkeypatch):
    """End to end through FyersClient: many clients firing at once can only
    send as many requests as the shared per-second budget allows before
    they have to wait."""
    s = _settings()
    sent_at = []

    async def fake_sleep(seconds):
        clock.now += seconds * 1000

    monkeypatch.setattr(request_control.asyncio, "sleep", fake_sleep)

    def handler(request):
        sent_at.append(clock.now)
        return httpx.Response(200, json={"s": "ok"})

    clients = []
    for _ in range(3):
        c = FyersClient(settings=s)
        c._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(c)

    await asyncio.gather(*[clients[i % 3].get_data("/quotes", params={"symbols": "X"}) for i in range(20)])

    lim_s, _, _ = tier_limits(s, RequestPriority.INTERACTIVE)
    assert len(sent_at) == 20
    # The limiter's own admission log (the Redis minute window) is the
    # ground truth for when each request was admitted: no 1-second span
    # ever contains more admissions than the shared per-second budget.
    from app.db.redis_client import get_redis

    admitted = [score for _, score in await get_redis().zrange(request_control._KEY_MINUTE, 0, -1, withscores=True)]
    assert len(admitted) == 20
    for t in admitted:
        assert sum(1 for u in admitted if t <= u < t + 1000) <= lim_s


# ---- priorities --------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_cannot_consume_critical_headroom(clock):
    s = _settings()
    limiter = request_control.get_rate_limiter()
    bg_s, _, _ = tier_limits(s, RequestPriority.BACKGROUND)

    for _ in range(bg_s):
        assert (await limiter._admit(s, RequestPriority.BACKGROUND, force=False))[1] == ADMITTED
    assert (await limiter._admit(s, RequestPriority.BACKGROUND, force=False))[1] == WAIT_WINDOW
    assert (await limiter._admit(s, RequestPriority.CRITICAL, force=False))[1] == ADMITTED


@pytest.mark.asyncio
async def test_auth_is_never_blocked_but_is_counted(clock):
    s = _settings()
    limiter = request_control.get_rate_limiter()
    crit_s, _, _ = tier_limits(s, RequestPriority.CRITICAL)
    for _ in range(crit_s):
        await limiter._admit(s, RequestPriority.CRITICAL, force=False)
    await limiter.note_provider_429(s)  # even during a 429 cooldown

    await limiter.acquire(s, RequestPriority.AUTH, "profile")  # returns immediately, no exception

    counts = await limiter.window_counts()
    assert counts["today_ist"] == crit_s + 1


@pytest.mark.asyncio
async def test_priority_context_applies_to_new_clients(clock):
    s = _settings()
    with fyers_priority(RequestPriority.BACKGROUND):
        assert FyersClient(settings=s).priority == RequestPriority.BACKGROUND
    assert FyersClient(settings=s).priority == RequestPriority.INTERACTIVE
    assert FyersClient(settings=s, priority=RequestPriority.CRITICAL).priority == RequestPriority.CRITICAL


# ---- explicit failure, waiting ------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_waits_then_proceeds(clock, monkeypatch):
    s = _settings()
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        clock.now += seconds * 1000

    monkeypatch.setattr(request_control.asyncio, "sleep", fake_sleep)
    limiter = request_control.get_rate_limiter()
    lim_s, _, _ = tier_limits(s, RequestPriority.INTERACTIVE)
    for _ in range(lim_s):
        await limiter.acquire(s, RequestPriority.INTERACTIVE, "quotes")
    assert slept == []
    await limiter.acquire(s, RequestPriority.INTERACTIVE, "quotes")
    assert len(slept) == 1


@pytest.mark.asyncio
async def test_exceeding_max_wait_fails_explicitly_and_request_is_never_sent(clock):
    s = _settings()
    limiter = request_control.get_rate_limiter()
    _, enr_m, _ = tier_limits(s, RequestPriority.ENRICHMENT)
    enr_s, _, _ = tier_limits(s, RequestPriority.ENRICHMENT)
    admitted = 0
    while admitted < enr_m:  # fill the ENRICHMENT minute budget
        for _ in range(enr_s):
            if admitted < enr_m:
                await limiter._admit(s, RequestPriority.ENRICHMENT, force=False)
                admitted += 1
        clock.now += 1001

    calls: dict = {}
    client = _ok_client(s, calls, priority=RequestPriority.ENRICHMENT)
    with pytest.raises(FyersLocalCapacityExceeded):
        await client.get_data("/quotes", params={"symbols": "X"})
    assert calls.get("n", 0) == 0  # never sent, and not retried


@pytest.mark.asyncio
async def test_daily_ceiling_rejects(clock):
    s = _settings(fyers_limit_per_day=3)
    limiter = request_control.get_rate_limiter()
    for _ in range(3):
        clock.now += 1001
        await limiter.acquire(s, RequestPriority.CRITICAL, "quotes")
    assert (await limiter._admit(s, RequestPriority.CRITICAL, force=False))[1] == DAY_EXHAUSTED
    with pytest.raises(FyersLocalCapacityExceeded):
        await limiter.acquire(s, RequestPriority.CRITICAL, "quotes")


# ---- 429 handling ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_429_starts_global_cooldown_and_is_metered(clock, monkeypatch):
    s = _settings()

    async def no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)  # tenacity backoff

    calls: dict = {}
    client = _ok_client(s, calls, status=429, body={"s": "error", "message": "rate limited"},
                        priority=RequestPriority.INTERACTIVE)
    # With a 5s cooldown and a stubbed tenacity sleep, the retry hits the
    # cooldown; INTERACTIVE may wait (clock doesn't advance via tenacity),
    # so give the limiter's own sleep a clock-advancing stub.

    async def limiter_sleep(seconds):
        clock.now += seconds * 1000

    monkeypatch.setattr(request_control.asyncio, "sleep", limiter_sleep)

    with pytest.raises(FyersRateLimitError):
        await client.get_data("/quotes", params={"symbols": "X"})

    limiter = request_control.get_rate_limiter()
    wait_ms, code = await limiter._admit(s, RequestPriority.CRITICAL, force=False)
    assert code == COOLDOWN and wait_ms > 0

    snap = await usage_snapshot(s)
    assert snap["totals"]["request:quotes"]["rate_limited_429"] >= 1


# ---- metering ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metering_counts_success_401_and_cache_hits_without_secrets(clock):
    s = _settings()
    calls: dict = {}
    await _ok_client(s, calls).get_data("/quotes", params={"symbols": "X"})
    await _ok_client(s, calls).get_data("/history", params={"symbol": "X"})

    unauthorized = _ok_client(s, calls, status=401, body={"s": "error"})
    with pytest.raises(Exception):
        await unauthorized.get_data("/depth", params={"symbol": "X"})

    await request_control.record_cache_hit("quotes")

    snap = await usage_snapshot(s)
    totals = snap["totals"]
    assert totals["request:quotes"]["success"] == 1
    assert totals["request:history"]["success"] == 1
    assert totals["request:depth"]["unauthorized_401"] >= 1
    assert totals["request:quotes"]["cache_hit"] == 1
    assert snap["limiter_backend"] == "redis"
    assert snap["current_window"]["today_ist"] >= 3

    dumped = json.dumps(snap)
    assert FAKE_TOKEN not in dumped
    assert "test-client:" not in dumped  # no Authorization header value
    # The token really was sent on the wire (so the check above is meaningful).
    assert any(FAKE_TOKEN in h.get("authorization", "") for h in calls["headers"])


@pytest.mark.asyncio
async def test_usage_endpoint_returns_diagnostics(app_client):
    resp = await app_client.get("/api/diagnostics/fyers-usage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_limits"] == {"per_second": 10, "per_minute": 200, "per_day": 100000}
    assert set(body["priority_tiers"]) == {p.value for p in RequestPriority}
    assert body["priority_tiers"]["AUTH"]["blocking"] is False


# ---- degraded mode -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_falls_back_to_local_limiter_when_redis_unavailable(clock, monkeypatch):
    def broken_redis():
        raise ConnectionError("redis down")

    monkeypatch.setattr(request_control, "get_redis", broken_redis)
    s = _settings()
    limiter = request_control.get_rate_limiter()
    lim_s, _, _ = tier_limits(s, RequestPriority.INTERACTIVE)

    codes = [(await limiter._admit(s, RequestPriority.INTERACTIVE, force=False))[1] for _ in range(lim_s + 1)]
    assert codes[:lim_s] == [ADMITTED] * lim_s
    assert codes[-1] == WAIT_WINDOW
    assert limiter.backend == "local_fallback"

    snap = await usage_snapshot(s)
    assert snap["limiter_backend"] == "local_fallback"
    assert snap["metering_available"] is False
