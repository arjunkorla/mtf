"""GET /api/health"""

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_redis_dep
from app.config import get_settings
from app.integrations.fyers.session import CONNECTED, MOCK, get_session_manager
from app.schemas.health import ComponentHealth, HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis_dep)) -> HealthResponse:
    settings = get_settings()
    components = []

    try:
        await db.execute(text("SELECT 1"))
        components.append(ComponentHealth(name="database", status="ok"))
    except Exception as exc:  # noqa: BLE001
        components.append(ComponentHealth(name="database", status="down", detail=str(exc)[:200]))

    try:
        await redis.ping()
        components.append(ComponentHealth(name="redis", status="ok"))
    except Exception as exc:  # noqa: BLE001
        components.append(ComponentHealth(name="redis", status="down", detail=str(exc)[:200]))

    # Session state from the local token store -- no FYERS request per health
    # check. "Credentials configured" never meant "credentials valid"; the
    # detail is now the actual session status (CONNECTED / REFRESH_REQUIRED /
    # LOGIN_REQUIRED / MOCK / ERROR). Use /api/fyers/status?verify=true for a
    # real (cached) round-trip.
    fyers_status = get_session_manager(settings).status_code()
    components.append(
        ComponentHealth(
            name="fyers",
            status="ok" if fyers_status in (CONNECTED, MOCK) else "degraded",
            detail=fyers_status,
        )
    )

    overall = "ok" if all(c.status != "down" for c in components) else "degraded"
    return HealthResponse(status=overall, app_env=settings.app_env, components=components)
