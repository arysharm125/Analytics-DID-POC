from attr import dataclass
from fastapi import APIRouter
from pydantic import BaseModel, Field
from app.services.vault import vault_is_authenticated
from app.version import VERSION, full_version


# -------------------------
# Health
# -------------------------
class HealthResponse(BaseModel):
    status: str = Field(
        ...,
        description="Whether the service is running ok",
    )
    vault_authenticated: bool = Field(
        ...,
        description="Whether the service has authenticated to vault",
    )
    version : str = Field(
        ...,
        description="Backend service version",
    )
    full_version : str = Field(
        ...,
        description="Backend service version and build metadata (full version string)",
    )
    pass

app = APIRouter(tags=["Health"])

@app.get("/health")
def health() -> HealthResponse:
    """Returns a health status for the application."""
    try:
        vault_ok = vault_is_authenticated()
    except Exception:
        vault_ok = False

    return HealthResponse(
        status="ok",
        vault_authenticated=vault_ok,
        version=VERSION,
        full_version=full_version(),
    )
