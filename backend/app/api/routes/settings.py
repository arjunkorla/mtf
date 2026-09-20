"""GET/PUT /api/settings"""

from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from app.api.deps import get_redis_dep
from app.schemas.settings import ScannerSettings
from app.services.settings_service import get_scanner_settings, update_scanner_settings

router = APIRouter()


@router.get("/settings", response_model=ScannerSettings)
async def read_settings(redis: Redis = Depends(get_redis_dep)) -> ScannerSettings:
    return await get_scanner_settings(redis)


@router.put("/settings", response_model=ScannerSettings)
async def write_settings(
    settings: ScannerSettings, redis: Redis = Depends(get_redis_dep)
) -> ScannerSettings:
    return await update_scanner_settings(redis, settings)
