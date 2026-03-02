import asyncio
import logging
import logging.config
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import get_config
from app.middlewares import exception_handler_middleware, http_exception_handler
from app.request_id import AccessLogMiddleware, RequestIdFilter, RequestIdMiddleware

# from app.routers.policy import router as policy_router
from app.routers.advisory_router import router as advisory_router
from app.routers.dependencies import did_service_lifespan
from app.routers.didcheck import app as didcheck_router
from app.routers.epdw import app as did_router
from app.routers.epdw import startup_did_router
from app.routers.health import app as health_router
from app.version import VERSION

# ==========================
# Logging
# ==========================
logging.config.fileConfig("deployment/logging.ini", disable_existing_loggers=False)

# Apply RequestIdFilter to all handlers programmatically
# This ensures all loggers (including uvicorn) have the filter
request_id_filter = RequestIdFilter()
for handler in logging.root.handlers:
    handler.addFilter(request_id_filter)

logging.getLogger("pymongo").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger = logging.getLogger("deployment")


# ==========================
# FastAPI App
# ==========================

async def _pool_monitor_task(interval: int) -> None:
    """Background task to periodically log MongoDB pool statistics.

    Args:
        interval: Time in seconds between each pool stats log
    """
    from app.routers.dependencies import get_db

    while True:
        await asyncio.sleep(interval)
        try:
            db = get_db()
            stats = db.get_pool_stats()
            if stats:
                logger.info(
                    f"MongoDB Pool: {stats.in_use_count}/{stats.max_pool_size} in use, "
                    f"{stats.available_count} available, "
                    f"wait_queue={stats.wait_queue_size}, "
                    f"health={stats.pool_health}"
                )
                # Log warning if pool health is not healthy
                if stats.pool_health == "warning":
                    logger.warning(
                        f"Pool health WARNING: {stats.in_use_count}/{stats.max_pool_size} "
                        f"({stats.in_use_count * 100 / stats.max_pool_size:.1f}%) in use"
                    )
                elif stats.pool_health == "critical":
                    logger.error(
                        f"Pool health CRITICAL: {stats.in_use_count}/{stats.max_pool_size} "
                        f"({stats.in_use_count * 100 / stats.max_pool_size:.1f}%) in use, "
                        f"wait_queue={stats.wait_queue_size}"
                    )
        except Exception as e:
            logger.debug(f"Pool stats monitoring error: {e}")


@asynccontextmanager
async def _app_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
  """App lifespan generator with startup validation and graceful shutdown."""
  async with AsyncExitStack() as stack:
    # === STARTUP VALIDATION ===
    logger.info("Starting application - validating dependencies...")

    # 1. Validate vault connectivity
    try:
      from app.routers.dependencies import get_vault
      get_vault()
      # Vault is initialized - test basic connectivity
      logger.info("✓ Vault connection established")
    except Exception as e:
      logger.critical(f"✗ Vault connection failed: {e}")
      raise RuntimeError("Failed to connect to vault - aborting startup") from e

    # 2. Validate database connectivity
    try:
      from app.routers.dependencies import get_db
      db = get_db()
      if db.client is not None:
        db.client.admin.command("ping")
        logger.info("✓ MongoDB connection established")
      else:
        raise RuntimeError("MongoDB client is None")
    except Exception as e:
      logger.critical(f"✗ MongoDB connection failed: {e}")
      raise RuntimeError("Failed to connect to MongoDB - aborting startup") from e

    # 3. Run migrations and other initialization
    await startup_did_router()
    await stack.enter_async_context(did_service_lifespan())

    # 4. Start background pool monitoring task
    config = get_config()
    pool_monitor_interval = config.mongo_pool.pool_monitor_interval_s
    pool_monitor = asyncio.create_task(_pool_monitor_task(pool_monitor_interval))
    logger.info(f"✓ Pool monitoring task started (interval: {pool_monitor_interval}s)")

    logger.info("Application startup complete")

    # Add additional lifespans above this point.
    yield

    # === GRACEFUL SHUTDOWN ===
    logger.info("Shutting down application...")

    # Cancel background monitoring task
    pool_monitor.cancel()
    try:
        await pool_monitor
    except asyncio.CancelledError:
        logger.info("✓ Pool monitoring task stopped")

    # Close database connections
    try:
      from app.routers.dependencies import _db_connector
      if _db_connector and _db_connector.client:
        _db_connector.close_connection()
        logger.info("✓ MongoDB connection closed")
    except Exception as e:
      logger.warning(f"Error closing MongoDB connection: {e}")

    logger.info("Application shutdown complete")


app = FastAPI(docs_url=None, redoc_url=None, lifespan=_app_lifespan, version=VERSION)

# ==========================
# Middleware
# ==========================
# Access logging middleware (must be first to wrap entire request/response cycle)
app.add_middleware(AccessLogMiddleware)

# Request ID middleware (must be early to ensure all logs have request_id)
app.add_middleware(RequestIdMiddleware)

# ==========================
# Exception Handling
# ==========================
app.exception_handler(HTTPException)(http_exception_handler)
app.middleware("http")(exception_handler_middleware)


# app.include_router(policy_router)
app.include_router(did_router)
app.include_router(advisory_router)

# Conditionally include generic DID router based on feature flag
if get_config().features.didcheck_router:
  app.include_router(didcheck_router)

app.include_router(health_router)

@app.get("/docs", include_in_schema=False)
async def api_documentation(request: Request):
    return HTMLResponse("""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
    <title>Elements in HTML</title>

    <script src="https://unpkg.com/@stoplight/elements/web-components.min.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/@stoplight/elements/styles.min.css">
  </head>
  <body>

    <elements-api
      apiDescriptionUrl="openapi.json"
      router="hash"
    />

  </body>
</html>""")
