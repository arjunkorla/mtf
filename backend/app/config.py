"""Centralized application configuration.

All secrets and environment-specific values MUST come from environment
variables (see .env.example). Never hard-code credentials here.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # FYERS
    fyers_client_id: str = ""
    fyers_secret_key: str = ""
    fyers_redirect_uri: str = ""
    fyers_access_token: str = ""
    use_mock_fyers: bool = True

    # Database
    database_url: str = "postgresql+asyncpg://mtf:mtf@localhost:5432/mtf"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # AI
    ai_provider: str = "none"  # "anthropic" | "none"
    ai_api_key: str = ""

    # App
    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:8443"

    # Live market data (Phase 7 staleness investigation): a single
    # configurable freshness threshold rather than a hardcoded value
    # scattered across the live-data API/cache layer.
    live_data_stale_after_seconds: int = 30

    # Real-Time Confirmation Engine thresholds -- all experimental, all
    # overridable via env vars rather than buried in the service module.
    confirmation_near_invalidation_pct: float = 2.0  # within this % of invalidation counts as "near"
    confirmation_volume_expanding_ratio: float = 1.3  # volume_ratio >= this -> EXPANDING
    confirmation_volume_declining_ratio: float = 0.8  # volume_ratio <= this -> DECLINING
    confirmation_depth_strong_threshold: float = 0.3  # |depth_imbalance| >= this -> STRONG_*
    confirmation_depth_moderate_threshold: float = 0.1  # |depth_imbalance| >= this -> MODERATE_*
    confirmation_spread_wide_pct: float = 0.5  # spread_percentage above this -> WIDE
    confirmation_futures_flat_threshold_pct: float = 0.3  # |price or OI change %| below this -> FLAT
    confirmation_persistence_window: int = 5  # max observations retained per symbol
    confirmation_persistence_ttl_seconds: int = 3600  # observation history expires after this regardless

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
