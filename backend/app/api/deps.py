"""FastAPI dependency providers shared across route modules."""

from collections.abc import AsyncGenerator

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.redis_client import get_redis

DbDep = get_db


async def get_redis_dep() -> AsyncGenerator[Redis, None]:
    yield get_redis()


__all__ = ["get_db", "get_redis_dep", "AsyncSession"]
