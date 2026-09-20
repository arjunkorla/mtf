"""Aggregates all /api/* route modules (section 21) plus two additive,
non-contract routers: the Phase 5 live-quote WebSocket (live.py) and the
FYERS OAuth callback dev utility (fyers_auth.py) -- see each module's
docstring."""

from fastapi import APIRouter

from app.api.routes import fyers_auth, health, live, market, position_sizing, scanner, settings, stocks

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(scanner.router, tags=["scanner"])
api_router.include_router(stocks.router, tags=["stocks"])
api_router.include_router(position_sizing.router, tags=["risk"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(live.router, tags=["live"])
api_router.include_router(market.router, tags=["market-data"])
api_router.include_router(fyers_auth.router, tags=["fyers-auth"])
