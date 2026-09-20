from pydantic import BaseModel


class ComponentHealth(BaseModel):
    name: str
    status: str  # "ok" | "degraded" | "down"
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    app_env: str
    components: list[ComponentHealth]
