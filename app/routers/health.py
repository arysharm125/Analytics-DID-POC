from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.routers.dependencies import MongoConnectorDep
from app.services.vault import vault_is_authenticated
from app.version import VERSION, full_version


# -------------------------
# Health
# -------------------------
class HealthResponse(BaseModel):
    status: str = Field(
        ...,
        description="Service health status: 'ok', 'degraded', or 'unhealthy'",
    )
    vault_authenticated: bool = Field(
        ...,
        description="Whether the service has authenticated to vault",
    )
    db_connected: bool = Field(
        ...,
        description="Whether the service can connect to MongoDB",
    )
    version: str = Field(
        ...,
        description="Backend service version",
    )
    full_version: str = Field(
        ...,
        description="Backend service version and build metadata (full version string)",
    )


app = APIRouter(tags=["Health"])


@app.get("/health")
def health(db: MongoConnectorDep) -> HealthResponse:
    """Returns a health status for the application.

    Checks:
    - Vault authentication status
    - MongoDB connectivity (ping command)

    Returns:
    - status "ok": All dependencies healthy
    - status "degraded": DB connected but vault unavailable
    - status "unhealthy": DB unavailable
    """
    # Check vault authentication
    try:
        vault_ok = vault_is_authenticated()
    except Exception:
        vault_ok = False

    # Check MongoDB connectivity
    try:
        if db.client is not None:
            db.client.admin.command("ping")
            db_ok = True
        else:
            db_ok = False
    except Exception:
        db_ok = False

    # Determine overall status
    if vault_ok and db_ok:
        status = "ok"
    elif db_ok:  # DB up but vault down - can still serve some requests
        status = "degraded"
    else:
        status = "unhealthy"

    return HealthResponse(
        status=status,
        vault_authenticated=vault_ok,
        db_connected=db_ok,
        version=VERSION,
        full_version=full_version(),
    )
