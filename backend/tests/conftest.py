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
