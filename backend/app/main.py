"""FastAPI application entrypoint.

Frontend contract (section 28): the React app talks to this service only
through VITE_API_BASE_URL, e.g. http://localhost:8000/api. Response shapes
are Pydantic models (app/schemas/*) and are expected to stay stable.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import get_settings
from app.core.exceptions import FyersAuthRequiredError, MtfError
from app.logging_config import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MTF backend | app_env=%s | use_mock_fyers=%s", settings.app_env, settings.use_mock_fyers)
    # Local check only (no FYERS call): never forces a login at startup.
    from app.integrations.fyers.session import get_session_manager

    logger.info("FYERS session status at startup: %s", get_session_manager().status_code())

    # Phase B suggestion tracker: a no-op unless ENABLE_SUGGESTION_TRACKER=true
    # (and it refuses mock FYERS data).
    from app.services.suggestion_tracker_service import get_suggestion_tracker

    tracker = get_suggestion_tracker()
    await tracker.start()
    # Phase D daily evidence collection: a no-op unless ENABLE_MTF_DAILY_COLLECTION=true.
    from app.services.mtf_daily_collection_service import get_daily_collector

    collector = get_daily_collector()
    await collector.start()
    try:
        yield
    finally:
        await collector.stop()
        await tracker.stop()


app = FastAPI(
    title="AI MTF Stock Recommendation Engine",
    description="NSE MTF research backend -- not a trading terminal, no order execution.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["*"],
)

# Starlette's ServerErrorMiddleware (which handles unhandled exceptions) sits
# outside CORSMiddleware, so its fallback response bypasses CORS header
# injection entirely -- the browser then blocks it as a CORS failure and
# fetch() surfaces a generic network error, indistinguishable from the
# backend being down. Registering explicit handlers routes these through
# Starlette's ExceptionMiddleware instead, which runs inside CORSMiddleware,
# so the real status/detail actually reaches the frontend.
@app.exception_handler(FyersAuthRequiredError)
async def fyers_auth_required_handler(request: Request, exc: FyersAuthRequiredError) -> JSONResponse:
    """A dead FYERS session is a user action (reconnect), not a 502 upstream
    failure -- give the frontend a stable code to show "Connect FYERS"."""
    from app.integrations.fyers.session import LOGIN_PATH, get_session_manager

    logger.warning("FYERS auth required on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=401,
        content={
            "detail": str(exc),
            "code": FyersAuthRequiredError.code,
            "fyers_status": get_session_manager().status_code(),
            "login_url": LOGIN_PATH,
        },
    )


@app.exception_handler(MtfError)
async def mtf_error_handler(request: Request, exc: MtfError) -> JSONResponse:
    logger.error("%s on %s %s: %s", type(exc).__name__, request.method, request.url.path, exc)
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.include_router(api_router)
