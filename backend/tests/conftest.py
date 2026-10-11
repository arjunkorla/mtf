"""Shared test fixtures.

Forces USE_MOCK_FYERS=true and a SQLite in-memory DATABASE_URL before any
`app.*` module is imported, so the whole test suite runs without real
FYERS credentials, PostgreSQL, or Redis (section 27) -- unconditionally,
not just as a default: a deployment .env with real live credentials
(USE_MOCK_FYERS=false, a real DATABASE_URL) is loaded into the container's
actual OS environment via docker-compose's env_file, so os.environ.setdefault
here was a no-op against it -- confirmed live, running `pytest` inside a
live-configured container silently made real FYERS calls and hung on rate
limiting instead of running offline against mocks.
"""

import os

os.environ["USE_MOCK_FYERS"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["AI_PROVIDER"] = "none"
os.environ["APP_ENV"] = "test"
# Phase B/C feature flags: tests must see the safe defaults even when the
# container running them was started with the tracker/adapter enabled
# (observed 2026-09-29 during the controlled live validation).
os.environ["ENABLE_SUGGESTION_TRACKER"] = "false"
os.environ["ENABLE_MTF_SUGGESTION_ADAPTER"] = "false"
os.environ["MTF_SUGGESTION_DRY_RUN"] = "true"

# Redis isolation (Phase 5 test-isolation fix, 2026-09-21): service-level unit
# tests that call get_redis() directly (not via the app_client fixture's
# get_redis_dep override below) were writing real keys into the SAME Redis
# logical DB the live application uses -- confirmed live when a test's
# fabricated price=1.0 macro quote showed up in a real /tmp check script
# against backend-api-1 minutes later. DATABASE_URL is already safely swapped
# to an in-memory sqlite engine above; REDIS_URL gets the equivalent
# treatment here -- same server, but logical DB 15 (Redis' standalone-mode
# default is 16 DBs, 0-15; this project's only deployment target,
# docker-compose.yml's vanilla redis:7-alpine, supports this out of the box)
# instead of whatever index docker-compose's env_file/environment injected
# for production (db 0). This must run before any app.* import so
# get_settings()/get_redis() (both @lru_cache'd -- see app/config.py,
# app/db/redis_client.py) pick it up on their very first call.
TEST_REDIS_DB = 15
_prod_redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
os.environ["REDIS_URL"] = f"{_prod_redis_url.rsplit('/', 1)[0]}/{TEST_REDIS_DB}"

# FYERS session isolation: the runtime token store (backend/.runtime/
# fyers_session.json) holds the developer's REAL FYERS session. Tests get
# their own throwaway file and a blank legacy token, so nothing here can read,
# overwrite, or delete real credentials.
import tempfile
from pathlib import Path

TEST_FYERS_SESSION_FILE = Path(tempfile.mkdtemp(prefix="mtf-test-fyers-")) / "fyers_session.json"
os.environ["FYERS_SESSION_FILE"] = str(TEST_FYERS_SESSION_FILE)
os.environ["FYERS_ACCESS_TOKEN"] = ""

import pytest

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db


class _FakeRedis:
    """Minimal in-memory stand-in for redis.asyncio.Redis, used wherever the
    app depends on get_redis_dep during tests."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None):
        self._store[key] = value

    async def ping(self):
        return True


@pytest.fixture(autouse=True)
def _isolated_fyers_session():
    """Fresh, empty test session file and fresh session managers per test."""
    from app.integrations.fyers import session as fyers_session
    from app.integrations.fyers import token_store

    TEST_FYERS_SESSION_FILE.unlink(missing_ok=True)
    token_store._stores.clear()
    fyers_session.reset_session_managers()
    yield
    TEST_FYERS_SESSION_FILE.unlink(missing_ok=True)


@pytest_asyncio.fixture(autouse=True)
async def _isolated_redis_db():
    """Flushes ONLY the dedicated test Redis DB (see TEST_REDIS_DB/REDIS_URL
    above) before and after every test, so tests can't leak Redis state into
    each other across a run (repeated/parallel-safe) without ever touching
    the production DB index -- this connection is physically incapable of
    reaching db 0's keys, not just configured not to.

    get_redis() is @lru_cache'd (a deliberate process-wide singleton in
    production -- one process, one event loop). pytest-asyncio gives each
    test function its own fresh event loop
    (asyncio_default_fixture_loop_scope="function" in pyproject.toml), so
    reusing that cached client's connection pool across tests reuses
    asyncio primitives bound to a previous, now-closed loop -- confirmed
    live: making this fixture autouse without clearing the cache first broke
    135 otherwise-unrelated tests with a hung/errored Redis read. Clearing
    the cache here forces a fresh client, bound to the current test's own
    loop, every time -- this is a test-only workaround for pytest-asyncio's
    per-function loop model, not a change to production's caching."""
    from app.db.redis_client import get_redis

    get_redis.cache_clear()
    redis = get_redis()
    await redis.flushdb()
    yield
    # Deliberately nothing on the way out (no flush, no aclose()). A
    # background-thread-driven test (e.g. test_live_websocket.py's
    # LiveDataHub tests, which run the ASGI app through httpx's own
    # anyio portal -- a genuinely different event loop from this fixture's)
    # can still have a run_coroutine_threadsafe-scheduled tick callback
    # touching this same lru_cache'd client when the test function returns.
    # Confirmed live: awaiting anything on it here raced with that and
    # turned an already-tolerated (cache_service.py logs and swallows it)
    # cross-loop warning into a hard "Event loop is closed" test failure.
    # Isolation doesn't need a teardown step: the NEXT test's setup above
    # unconditionally clears the cache and starts from a fresh, flushed
    # client, so nothing here needs to leave things tidy on the way out.


@pytest_asyncio.fixture
async def db_session():
    # Base.metadata only knows about a model once its module has actually
    # been imported (SQLAlchemy declarative registration is a side effect of
    # class-body execution). Without this, create_all() below silently omits
    # any table whose model module nothing has imported yet in this process
    # -- e.g. ScannerRun, only ever imported transitively via `app.main` ->
    # api routes -> scanner_service. That import normally happens to occur
    # before this fixture first runs (test_api_health.py sorts first
    # alphabetically and imports app.main via its own app_client fixture),
    # which masked this for every test file except when one runs alone.
    import app.main  # noqa: F401

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def app_client(db_session):
    from app.api.deps import get_redis_dep
    from app.main import app

    async def _override_get_db():
        yield db_session

    fake_redis = _FakeRedis()

    async def _override_get_redis_dep():
        yield fake_redis

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis_dep] = _override_get_redis_dep

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()
