"""GET /api/fyers/callback -- manual local-dev utility that completes the
FYERS OAuth auth-code flow (see app/integrations/fyers/auth.py's
build_authcode_url/exchange_auth_code, which existed but weren't wired to
any route). Not part of the original 8-endpoint frontend contract and never
called by the frontend app -- it exists only so a developer's own browser
has somewhere local to land after logging into FYERS, so the resulting
auth_code can be exchanged for an access_token without a public redirect
target.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.core.exceptions import FyersAuthError
from app.integrations.fyers.auth import exchange_auth_code

router = APIRouter()

# app/api/routes/fyers_auth.py -> parents[3] is the backend/ dir (== /app
# inside the container, per docker-compose.yml's ".:/app" bind mount), the
# same directory Settings(env_file=".env") already reads from.
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def _persist_access_token(token: str) -> None:
    """Writes FYERS_ACCESS_TOKEN into the existing .env in place, never
    logging or returning the value itself."""
    lines = _ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("FYERS_ACCESS_TOKEN="):
            lines[i] = f"FYERS_ACCESS_TOKEN={token}\n"
            break
    else:
        lines.append(f"FYERS_ACCESS_TOKEN={token}\n")
    _ENV_PATH.write_text("".join(lines), encoding="utf-8")


@router.get("/fyers/callback")
async def fyers_callback(auth_code: str = Query(...), state: str | None = None) -> dict:
    try:
        access_token = await exchange_auth_code(auth_code)
    except FyersAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    _persist_access_token(access_token)

    return {
        "status": "ok",
        "message": (
            "FYERS access token obtained and stored in backend/.env. USE_MOCK_FYERS is "
            "unchanged -- it must be flipped and the api container recreated as a separate, "
            "deliberate step before it's used for live calls."
        ),
    }
