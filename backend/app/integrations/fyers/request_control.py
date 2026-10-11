"""Process-wide FYERS REST request control (Phase 0): one shared rate limiter
plus request metering for every FyersClient instance and every caller
(MTF scanner, research collection, future intraday/MCX scanners, the future
suggestion tracker, frontend-triggered calls).

Why this replaced FyersClient's old per-instance throttle: that throttle
lived on each FyersClient, and a fresh client is created per scanner run /
per request, so two concurrent callers each got their own 8/sec budget and
nothing enforced FYERS' per-minute cap at all. Provider limits (confirmed
live, see fyers_client.py): 10 req/sec, 200 req/min, 100,000 req/day --
breaching the per-minute cap 3x in a day blocks the account for the rest of
the day.

Design:
  - Sliding-window counters for 1 second and 60 seconds, plus an IST-date
    daily counter, checked-and-recorded atomically by ONE Redis Lua script,
    so every process/client sharing this Redis shares one budget. Time comes
    from the Redis server clock (TIME), not each process's clock.
  - Safety ceilings (Settings.fyers_limit_*) sit below the provider limits.
  - Priority tiers are implemented as tier-specific ceilings (a fraction of
    the safety ceiling), not a priority queue: a lower tier can never
    consume the headroom reserved for a higher tier, and there is no
    scheduler/queue state to get wrong across processes. AUTH is never
    blocked (it is recorded in the window, but never waits or fails), so
    session verification can't get trapped behind market-data traffic.
  - When the tier's budget is exhausted the caller waits (bounded by a
    per-tier max wait); if it still can't be admitted it gets
    FyersLocalCapacityExceeded -- an explicit failure, never fabricated data.
  - A real HTTP 429 from FYERS starts a short global cooldown for every
    non-AUTH tier.
  - If Redis is unreachable, an in-process limiter with the same algorithm
    takes over (still correct for this single-worker deployment -- see
    live_data_hub.py), and the diagnostics say so.

Metering never records tokens, PINs, headers or secrets -- only
category/outcome counters in hourly IST buckets.
"""

import asyncio
import contextlib
import contextvars
import datetime as dt
import threading
import time
import uuid
from collections import deque
from enum import StrEnum

from app.config import Settings, get_settings
from app.core.exceptions import FyersLocalCapacityExceeded
from app.db.redis_client import get_redis
from app.logging_config import get_logger

logger = get_logger(__name__)

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

# Provider limits, recorded for diagnostics only -- enforcement always uses
# the lower Settings.fyers_limit_* safety ceilings.
PROVIDER_LIMIT_PER_SECOND = 10
PROVIDER_LIMIT_PER_MINUTE = 200
PROVIDER_LIMIT_PER_DAY = 100_000


class RequestPriority(StrEnum):
    AUTH = "AUTH"  # session verification / recovery -- never blocked
    CRITICAL = "CRITICAL"  # active-suggestion risk/stop reconciliation
    INTERACTIVE = "INTERACTIVE"  # user-requested scanner / analysis
    BACKGROUND = "BACKGROUND"  # scheduled research collection, outcome backfill
    ENRICHMENT = "ENRICHMENT"  # non-critical enrichment


# Fraction of the safety ceiling each tier may use (per-second and
# per-minute). The daily ceiling is shared by all non-AUTH tiers.
PRIORITY_CEILING_FRACTION: dict[RequestPriority, float] = {
    RequestPriority.AUTH: 1.0,
    RequestPriority.CRITICAL: 1.0,
    RequestPriority.INTERACTIVE: 0.9,
    RequestPriority.BACKGROUND: 0.6,
    RequestPriority.ENRICHMENT: 0.4,
}

PRIORITY_MAX_WAIT_SECONDS: dict[RequestPriority, float] = {
    RequestPriority.AUTH: 0.0,
    RequestPriority.CRITICAL: 30.0,
    RequestPriority.INTERACTIVE: 90.0,
    RequestPriority.BACKGROUND: 120.0,
    RequestPriority.ENRICHMENT: 20.0,
}

_current_priority: contextvars.ContextVar[RequestPriority] = contextvars.ContextVar(
    "fyers_request_priority", default=RequestPriority.INTERACTIVE
)


def current_priority() -> RequestPriority:
    return _current_priority.get()


@contextlib.contextmanager
def fyers_priority(priority: RequestPriority):
    """Sets the priority for every FyersClient request made inside this
    block (including ones made deep inside services that create their own
    FyersClient) without threading a parameter through them."""
    token = _current_priority.set(priority)
    try:
        yield
    finally:
        _current_priority.reset(token)


def categorize_path(path: str) -> str:
    for prefix, category in (
        ("/quotes", "quotes"),
        ("/history", "history"),
        ("/depth", "depth"),
        ("/options-chain", "options_chain"),
        ("/profile", "profile"),
        ("/span_margin", "margin"),
    ):
        if path.startswith(prefix):
            return category
    return "other"


def tier_limits(settings: Settings, priority: RequestPriority) -> tuple[int, int, int]:
    frac = PRIORITY_CEILING_FRACTION[priority]
    per_second = max(1, int(settings.fyers_limit_per_second * frac))
    per_minute = max(1, int(settings.fyers_limit_per_minute * frac))
    return per_second, per_minute, settings.fyers_limit_per_day


# ---- keys -----------------------------------------------------------------

_KEY_SECOND = "mtf:fyers:rl:second"
_KEY_MINUTE = "mtf:fyers:rl:minute"
_KEY_COOLDOWN = "mtf:fyers:rl:cooldown"


def _day_key(now_ist: dt.datetime) -> str:
    return f"mtf:fyers:rl:day:{now_ist:%Y%m%d}"


def _meter_key(now_ist: dt.datetime) -> str:
    return f"mtf:fyers:meter:{now_ist:%Y%m%d%H}"


# Return codes from the admission check.
ADMITTED = 0
WAIT_WINDOW = 1
DAY_EXHAUSTED = 3
COOLDOWN = 4

# KEYS: second zset, minute zset, day counter, cooldown key
# ARGV: now_ms ('' -> Redis server TIME), member, lim_s, lim_m, lim_d,
#       respect_cooldown (0/1), force (0/1)
# Returns {wait_ms, code}.
_ADMIT_LUA = """
local now
if ARGV[1] == '' then
  local t = redis.call('TIME')
  now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
else
  now = tonumber(ARGV[1])
end
local member = ARGV[2]
local lim_s = tonumber(ARGV[3])
local lim_m = tonumber(ARGV[4])
local lim_d = tonumber(ARGV[5])
local respect_cooldown = tonumber(ARGV[6])
local force = tonumber(ARGV[7])

if force == 0 and respect_cooldown == 1 then
  local until_ms = tonumber(redis.call('GET', KEYS[4]) or '0')
  if until_ms > now then return {until_ms - now, 4} end
end

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - 60000)
local cs = redis.call('ZCARD', KEYS[1])
local cm = redis.call('ZCARD', KEYS[2])
local cday = tonumber(redis.call('GET', KEYS[3]) or '0')

if force == 0 then
  if cday >= lim_d then return {-1, 3} end
  local wait = 0
  if cs >= lim_s then
    local o = redis.call('ZRANGE', KEYS[1], cs - lim_s, cs - lim_s, 'WITHSCORES')
    wait = math.max(wait, tonumber(o[2]) + 1000 - now)
  end
  if cm >= lim_m then
    local o = redis.call('ZRANGE', KEYS[2], cm - lim_m, cm - lim_m, 'WITHSCORES')
    wait = math.max(wait, tonumber(o[2]) + 60000 - now)
  end
  if wait > 0 then return {math.ceil(wait), 1} end
end

redis.call('ZADD', KEYS[1], now, member)
redis.call('PEXPIRE', KEYS[1], 2000)
redis.call('ZADD', KEYS[2], now, member)
redis.call('PEXPIRE', KEYS[2], 61000)
redis.call('INCR', KEYS[3])
redis.call('EXPIRE', KEYS[3], 172800)
return {0, 0}
"""

# Same clock source as _ADMIT_LUA. KEYS: cooldown key. ARGV: now_ms ('' ->
# Redis TIME), cooldown_ms. Stores the cooldown's END time (not just a TTL)
# so admission compares it against the exact same clock.
_COOLDOWN_LUA = """
local now
if ARGV[1] == '' then
  local t = redis.call('TIME')
  now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
else
  now = tonumber(ARGV[1])
end
local cooldown_ms = tonumber(ARGV[2])
redis.call('SET', KEYS[1], string.format('%d', now + cooldown_ms), 'PX', string.format('%d', cooldown_ms + 60000))
return now + cooldown_ms
"""


class _LocalWindow:
    """In-process fallback with the same semantics as _ADMIT_LUA. Uses a
    threading lock (not asyncio) so it is safe across event loops."""

    def __init__(self):
        self._lock = threading.Lock()
        self.second: deque[float] = deque()
        self.minute: deque[float] = deque()
        self.day_counts: dict[str, int] = {}
        self.cooldown_until_ms: float = 0.0

    def admit(self, now_ms: float, day: str, lim_s: int, lim_m: int, lim_d: int, respect_cooldown: bool, force: bool) -> tuple[int, int]:
        with self._lock:
            if not force and respect_cooldown and self.cooldown_until_ms > now_ms:
                return int(self.cooldown_until_ms - now_ms), COOLDOWN
            while self.second and self.second[0] <= now_ms - 1000:
                self.second.popleft()
            while self.minute and self.minute[0] <= now_ms - 60000:
                self.minute.popleft()
            if not force:
                if self.day_counts.get(day, 0) >= lim_d:
                    return -1, DAY_EXHAUSTED
                wait = 0.0
                if len(self.second) >= lim_s:
                    wait = max(wait, self.second[len(self.second) - lim_s] + 1000 - now_ms)
                if len(self.minute) >= lim_m:
                    wait = max(wait, self.minute[len(self.minute) - lim_m] + 60000 - now_ms)
                if wait > 0:
                    return int(wait) + 1, WAIT_WINDOW
            self.second.append(now_ms)
            self.minute.append(now_ms)
            self.day_counts[day] = self.day_counts.get(day, 0) + 1
            return 0, ADMITTED


class FyersRateLimiter:
    """Process-wide singleton (see get_rate_limiter()). All state lives in
    Redis when reachable; `_local` is only the degraded-mode fallback."""

    def __init__(self, clock_ms=None):
        # clock_ms: test hook -- when set, its value is passed to the Lua
        # script instead of Redis server time, and used by the fallback.
        self._clock_ms = clock_ms
        self._local = _LocalWindow()
        self._script = None
        self._script_redis = None
        self.backend = "redis"

    def _now_ms(self) -> float:
        return self._clock_ms() if self._clock_ms is not None else time.time() * 1000

    async def _admit(self, settings: Settings, priority: RequestPriority, force: bool) -> tuple[int, int]:
        lim_s, lim_m, lim_d = tier_limits(settings, priority)
        now_ist = dt.datetime.now(IST)
        respect_cooldown = priority != RequestPriority.AUTH
        try:
            redis = get_redis()
            if self._script is None or self._script_redis is not redis:
                self._script = redis.register_script(_ADMIT_LUA)
                self._script_redis = redis
            now_arg = "" if self._clock_ms is None else str(int(self._clock_ms()))
            wait_ms, code = await self._script(
                keys=[_KEY_SECOND, _KEY_MINUTE, _day_key(now_ist), _KEY_COOLDOWN],
                args=[now_arg, uuid.uuid4().hex, lim_s, lim_m, lim_d, int(respect_cooldown), int(force)],
            )
            if self.backend != "redis":
                logger.info("FYERS rate limiter: Redis reachable again, leaving local fallback")
            self.backend = "redis"
            return int(wait_ms), int(code)
        except Exception as exc:  # noqa: BLE001 -- Redis down must not disable rate limiting
            if self.backend != "local_fallback":
                logger.warning("FYERS rate limiter: Redis unavailable (%s) -- using in-process fallback", type(exc).__name__)
            self.backend = "local_fallback"
            return self._local.admit(
                self._now_ms(), f"{now_ist:%Y%m%d}", lim_s, lim_m, lim_d, respect_cooldown, force
            )

    async def acquire(self, settings: Settings, priority: RequestPriority, category: str) -> None:
        """Blocks until one request of `priority` may be sent. AUTH is only
        recorded, never delayed. Raises FyersLocalCapacityExceeded when the
        tier cannot be admitted within its max wait (or the daily ceiling is
        exhausted) -- the request is then never sent."""
        if priority == RequestPriority.AUTH:
            await self._admit(settings, priority, force=True)
            return

        max_wait = PRIORITY_MAX_WAIT_SECONDS[priority]
        started = time.monotonic()
        waited_any = False
        while True:
            wait_ms, code = await self._admit(settings, priority, force=False)
            if code == ADMITTED:
                if waited_any:
                    await record_limiter_event(priority, "waited", (time.monotonic() - started) * 1000)
                return
            if code == DAY_EXHAUSTED:
                await record_limiter_event(priority, "rejected_daily_ceiling")
                raise FyersLocalCapacityExceeded(
                    f"FYERS daily request safety ceiling ({settings.fyers_limit_per_day}) reached; "
                    f"{category} request not sent"
                )
            elapsed = time.monotonic() - started
            sleep_s = max(wait_ms, 1) / 1000 + 0.005
            if elapsed + sleep_s > max_wait:
                await record_limiter_event(priority, "rejected_max_wait")
                raise FyersLocalCapacityExceeded(
                    f"FYERS request capacity for priority {priority.value} not available within "
                    f"{max_wait:.0f}s ({'429 cooldown' if code == COOLDOWN else 'rate window full'}); "
                    f"{category} request not sent"
                )
            waited_any = True
            await asyncio.sleep(sleep_s)

    async def note_provider_429(self, settings: Settings) -> None:
        """A real HTTP 429 from FYERS: every non-AUTH tier pauses briefly."""
        cooldown_s = settings.fyers_429_cooldown_seconds
        if cooldown_s <= 0:
            return
        now_arg = "" if self._clock_ms is None else str(int(self._clock_ms()))
        try:
            await get_redis().eval(_COOLDOWN_LUA, 1, _KEY_COOLDOWN, now_arg, int(cooldown_s * 1000))
        except Exception:  # noqa: BLE001
            self._local.cooldown_until_ms = self._now_ms() + cooldown_s * 1000
        await _meter_incr("limiter|GLOBAL|provider_429_cooldown_started")

    async def window_counts(self) -> dict:
        now_ist = dt.datetime.now(IST)
        if self.backend == "redis":
            try:
                redis = get_redis()
                if self._clock_ms is not None:
                    now_ms = int(self._clock_ms())
                else:
                    t = await redis.time()
                    now_ms = t[0] * 1000 + t[1] // 1000
                cooldown_until = float(await redis.get(_KEY_COOLDOWN) or 0)
                return {
                    "last_second": await redis.zcount(_KEY_SECOND, f"({now_ms - 1000}", "+inf"),
                    "last_minute": await redis.zcount(_KEY_MINUTE, f"({now_ms - 60000}", "+inf"),
                    "today_ist": int(await redis.get(_day_key(now_ist)) or 0),
                    "cooldown_remaining_ms": max(0, int(cooldown_until - now_ms)),
                }
            except Exception:  # noqa: BLE001
                pass
        now_ms = self._now_ms()
        return {
            "last_second": sum(1 for t in self._local.second if t > now_ms - 1000),
            "last_minute": sum(1 for t in self._local.minute if t > now_ms - 60000),
            "today_ist": self._local.day_counts.get(f"{now_ist:%Y%m%d}", 0),
            "cooldown_remaining_ms": max(0, int(self._local.cooldown_until_ms - now_ms)),
        }


_limiter: FyersRateLimiter | None = None


def get_rate_limiter() -> FyersRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = FyersRateLimiter()
    return _limiter


# ---- metering ---------------------------------------------------------------

OUTCOME_SUCCESS = "success"
OUTCOME_UNAUTHORIZED = "unauthorized_401"
OUTCOME_RATE_LIMITED = "rate_limited_429"
OUTCOME_HTTP_ERROR = "http_error"
OUTCOME_API_ERROR = "api_error"  # HTTP 2xx but FYERS "s" != ok
OUTCOME_TRANSPORT_ERROR = "transport_error"
OUTCOME_CACHE_HIT = "cache_hit"

_METER_TTL_SECONDS = 8 * 24 * 3600


async def _meter_incr(field: str, amount: int | float = 1) -> None:
    try:
        redis = get_redis()
        key = _meter_key(dt.datetime.now(IST))
        if isinstance(amount, float):
            await redis.hincrbyfloat(key, field, amount)
        else:
            await redis.hincrby(key, field, amount)
        await redis.expire(key, _METER_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 -- metering must never break a request
        logger.debug("FYERS metering write failed: %s", type(exc).__name__)


async def record_request(category: str, outcome: str, priority: RequestPriority | None = None) -> None:
    await _meter_incr(f"request|{category}|{outcome}")
    if priority is not None:
        await _meter_incr(f"priority|{priority.value}|sent")


async def record_cache_hit(category: str) -> None:
    await _meter_incr(f"request|{category}|{OUTCOME_CACHE_HIT}")


async def record_limiter_event(priority: RequestPriority, event: str, wait_ms: float | None = None) -> None:
    await _meter_incr(f"limiter|{priority.value}|{event}")
    if wait_ms is not None:
        await _meter_incr(f"limiter|{priority.value}|wait_ms_total", round(float(wait_ms), 1))


async def usage_snapshot(settings: Settings | None = None, hours: int = 24) -> dict:
    """Credential-free diagnostic view of FYERS request usage."""
    settings = settings or get_settings()
    limiter = get_rate_limiter()
    now_ist = dt.datetime.now(IST)

    buckets = []
    totals: dict[str, dict[str, float]] = {}
    try:
        redis = get_redis()
        for h in range(hours):
            bucket_time = now_ist - dt.timedelta(hours=h)
            raw = await redis.hgetall(_meter_key(bucket_time))
            if not raw:
                continue
            parsed: dict[str, dict[str, float]] = {}
            for field, value in raw.items():
                kind, name, metric = field.split("|", 2)
                group = f"{kind}:{name}"
                num = float(value)
                parsed.setdefault(group, {})[metric] = num
                totals.setdefault(group, {})
                totals[group][metric] = totals[group].get(metric, 0) + num
            buckets.append({"hour_ist": f"{bucket_time:%Y-%m-%d %H}:00", "counters": parsed})
        metering_available = True
    except Exception:  # noqa: BLE001
        metering_available = False

    return {
        "provider_limits": {
            "per_second": PROVIDER_LIMIT_PER_SECOND,
            "per_minute": PROVIDER_LIMIT_PER_MINUTE,
            "per_day": PROVIDER_LIMIT_PER_DAY,
        },
        "safety_ceilings": {
            "per_second": settings.fyers_limit_per_second,
            "per_minute": settings.fyers_limit_per_minute,
            "per_day": settings.fyers_limit_per_day,
            "provider_429_cooldown_seconds": settings.fyers_429_cooldown_seconds,
        },
        "priority_tiers": {
            p.value: {
                "per_second": tier_limits(settings, p)[0],
                "per_minute": tier_limits(settings, p)[1],
                "max_wait_seconds": PRIORITY_MAX_WAIT_SECONDS[p],
                "blocking": p != RequestPriority.AUTH,
            }
            for p in RequestPriority
        },
        "limiter_backend": limiter.backend,
        "current_window": await limiter.window_counts(),
        "metering_available": metering_available,
        "window_hours": hours,
        "totals": totals,
        "hourly": buckets,
        "generated_at_ist": now_ist.isoformat(),
    }
