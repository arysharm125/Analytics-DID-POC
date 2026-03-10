from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.database import ConnectionPoolStats
from app.routers.dependencies import MongoConnectorDep, VaultServiceDep
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
    pool_stats: ConnectionPoolStats | None = Field(
        None,
        description="MongoDB connection pool statistics (None if unavailable)",
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
def health(db: MongoConnectorDep, vault: VaultServiceDep) -> HealthResponse:
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
        vault_ok = vault.is_authenticated()
    except Exception:
        vault_ok = False

    # Check MongoDB connectivity and get pool stats
    pool_stats = None
    try:
        if db.client is not None:
            db.client.admin.command("ping")
            db_ok = True

            # Get pool statistics
            pool_stats = db.get_pool_stats()
        else:
            db_ok = False
    except Exception:
        db_ok = False

    # Determine overall status
    # Factor in pool health if available
    if vault_ok and db_ok:
        # Check pool health if stats available
        status = "degraded" if pool_stats and pool_stats.pool_health == "critical" else "ok"
    elif db_ok:  # DB up but vault down - can still serve some requests
        status = "degraded"
    else:
        status = "unhealthy"

    return HealthResponse(
        status=status,
        vault_authenticated=vault_ok,
        db_connected=db_ok,
        pool_stats=pool_stats,
        version=VERSION,
        full_version=full_version(),
    )
