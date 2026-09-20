"""GET/PUT /api/settings backing store (section 16/21).

Scanner thresholds are mutable at runtime, so they're kept in Redis (falling
back to an in-process singleton if Redis is unavailable) rather than in a
dedicated table -- there's exactly one settings document, not a dataset that
benefits from SQL. This never stores secrets; see schemas/settings.py.
"""

from redis.asyncio import Redis

from app.logging_config import get_logger
from app.schemas.settings import ScannerSettings

logger = get_logger(__name__)

_SETTINGS_KEY = "mtf:settings"
_fallback_settings = ScannerSettings()


async def get_scanner_settings(redis: Redis) -> ScannerSettings:
    global _fallback_settings
    try:
        raw = await redis.get(_SETTINGS_KEY)
        if raw:
            return ScannerSettings.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable for settings read, using in-process fallback: %s", exc)
    return _fallback_settings


async def update_scanner_settings(redis: Redis, settings: ScannerSettings) -> ScannerSettings:
    global _fallback_settings
    _fallback_settings = settings
    try:
        await redis.set(_SETTINGS_KEY, settings.model_dump_json())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis unavailable for settings write, kept in-process fallback only: %s", exc)
    return settings
