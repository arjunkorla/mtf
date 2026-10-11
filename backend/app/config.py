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
    # Legacy fallback only -- the live session (access/refresh tokens) is kept
    # in the runtime token store (app/integrations/fyers/token_store.py), not
    # here, so an OAuth login takes effect without recreating the container.
    fyers_access_token: str = ""
    use_mock_fyers: bool = True
    fyers_session_file: str = ""  # "" -> backend/.runtime/fyers_session.json
    # Where the OAuth callback page links back to after a successful login.
    frontend_url: str = "http://localhost:8443/"

    # FYERS request control (Phase 0, app/integrations/fyers/request_control.py).
    # Provider limits confirmed live: 10/sec, 200/min, 100,000/day (3 per-minute
    # breaches in a day block the account for the day) -- these safety ceilings
    # deliberately leave headroom below them and are shared by every process
    # and FyersClient instance via Redis.
    fyers_limit_per_second: int = 8
    fyers_limit_per_minute: int = 160
    fyers_limit_per_day: int = 80_000
    fyers_429_cooldown_seconds: float = 5.0

    # Suggestion tracker lifecycle rules (Phase A). Initial RESEARCH rules,
    # not statistically validated optima. Counted in real trading sessions
    # (app/data/session_calendar.py), never calendar days. Snapshotted onto
    # each suggestion at creation, so changing them never rewrites history.
    suggestion_mtf_entry_window_sessions: int = 5
    suggestion_mtf_max_holding_sessions: int = 20

    # Suggestion tracker (Phase B, app/services/suggestion_tracker_service.py).
    # OFF by default -- enabling it is an explicit operator decision.
    enable_suggestion_tracker: bool = False
    suggestion_tracker_bar_settle_seconds: int = 60  # a 5m bar is only used this long after it closes
    suggestion_tracker_session_close_grace_minutes: int = 10  # after 15:30 IST before a session counts as complete
    suggestion_tracker_idle_poll_seconds: int = 300  # wake interval outside market hours
    suggestion_tracker_flush_seconds: int = 30  # working-state flush interval (DB + Redis live view)
    suggestion_tracker_quote_fallback_seconds: int = 60  # batched quote fallback cadence when ticks are stale

    # MTF suggestion adapter (Phase C, app/services/mtf_suggestion_adapter.py).
    # Safe defaults: adapter OFF; when turned on it still only DRY-RUNS
    # (evaluates, persists nothing) until dry-run is explicitly disabled.
    enable_mtf_suggestion_adapter: bool = False
    mtf_suggestion_dry_run: bool = True

    # MTF daily evidence collection (Phase D, app/services/mtf_daily_collection_service.py).
    # SCAN runs once per session AFTER the close on completed daily candles
    # (the Phase D audit showed the forming candle changes scores, ranks and
    # level validity); GENERATE runs once at a fixed slot of the NEXT session
    # with a live generation price. The times are conventions held constant
    # for comparability across days -- not optimized values.
    enable_mtf_daily_collection: bool = False
    mtf_daily_collection_dry_run: bool = True
    mtf_daily_scan_time_ist: str = "16:00"
    mtf_daily_generate_time_ist: str = "09:30"
    mtf_daily_generate_deadline_ist: str = "10:30"
    mtf_daily_collection_poll_seconds: int = 60
    mtf_daily_scan_max_positions: int = 10
    mtf_daily_scan_capital: float = 500000.0  # only feeds position sizing, never selection
    mtf_daily_scan_risk_percent: float = 1.0
    mtf_daily_max_attempts: int = 3  # per stage/session, after failures/interruptions

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

    # Phase 6 research observation collection -- all overridable via env vars
    # rather than buried in the service module.
    live_subscription_settle_seconds: float = 5.0  # how long to let LiveDataHub cache populate before reading it
    research_collection_slots_ist: str = "09:30,10:30,11:30,12:30,13:30,14:30,15:15"
    research_slot_tolerance_minutes: int = 10  # how close to a configured slot "now" must be to trigger a collection

    # Momentum Scanner automation (MTF Momentum + Institutional Footprint
    # Scanner) -- intraday slots plus one EOD slot, the primary scan for
    # 1-4 week candidate identification. All overridable via env vars.
    momentum_scan_slots_ist: str = "09:20,10:30,12:30,14:30,15:15"
    momentum_scan_eod_time_ist: str = "16:00"
    momentum_scan_slot_tolerance_minutes: int = 5
    enable_momentum_scheduler: bool = True

    # Telegram alerting for the Momentum Scanner watchlist -- unset by
    # default, alerts are simply skipped (never fabricated/faked) until both
    # are configured.
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    enable_momentum_alerts: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
