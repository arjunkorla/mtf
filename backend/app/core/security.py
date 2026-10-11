"""Security helpers.

NOTE: Phase 1-5 ship without end-user authentication (internal research tool).
Section 29 of the spec requires authentication before production deployment.
This module is the placeholder seam where API-key or JWT auth should be
wired in; nothing here should leak secrets to callers.
"""

from fastapi import Request

SENSITIVE_KEYS = {
    "fyers_secret_key",
    "fyers_access_token",
    "access_token",
    "refresh_token",
    "pin",
    "database_url",
    "ai_api_key",
    "redis_url",
}


def scrub_secrets(payload: dict) -> dict:
    """Remove any keys that could leak credentials before returning to a client."""
    return {k: v for k, v in payload.items() if k.lower() not in SENSITIVE_KEYS}


async def require_internal_auth(request: Request) -> None:
    """Placeholder auth dependency.

    TODO(production): replace with real API-key/JWT validation before this
    service is exposed outside a trusted network. Intentionally a no-op in
    Phase 1-5 per the project spec (research tool, not a trading terminal).
    """
    return None
