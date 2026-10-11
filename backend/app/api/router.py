"""Aggregates all /api/* route modules (section 21) plus three additive,
non-contract routers: the Phase 5 live-quote WebSocket (live.py), the FYERS
OAuth callback dev utility (fyers_auth.py), and the Phase 5 EXPERIMENTAL
research confirmation layer (research.py) -- see each module's docstring."""

from fastapi import APIRouter

from app.api.routes import (
    diagnostics,
    fyers_auth,
    health,
    live,
    market,
    position_sizing,
    research,
    research_observations,
    scanner,
    settings,
    stocks,
    suggestions,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(scanner.router, tags=["scanner"])
api_router.include_router(stocks.router, tags=["stocks"])
api_router.include_router(position_sizing.router, tags=["risk"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(live.router, tags=["live"])
api_router.include_router(market.router, tags=["market-data"])
api_router.include_router(fyers_auth.router, tags=["fyers-auth"])
api_router.include_router(research.router, tags=["research"])
api_router.include_router(research_observations.router, tags=["research-observations"])
api_router.include_router(diagnostics.router, tags=["diagnostics"])
api_router.include_router(suggestions.router, tags=["suggestions"])
