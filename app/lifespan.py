"""Application lifespan management with injectable dependencies."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import AppConfig
    from app.database import MongoConnector
    from app.services.vault_service import VaultService


@dataclass
class StartupDependencies:
    """Injectable dependencies for application startup and lifespan.

    This allows testing the lifespan logic by injecting mock dependencies.
    """

    get_vault: Callable[[], "VaultService"]
    get_db: Callable[[], "MongoConnector"]
    did_service_lifespan: Callable[[], AbstractAsyncContextManager[None]]
    get_config: Callable[[], "AppConfig"]


def validate_vault_connectivity(get_vault: Callable[[], "VaultService"]) -> None:
    """Validate vault connection at startup.

    Args:
        get_vault: Callable that returns VaultService instance

    Raises:
        RuntimeError: If vault connection fails
    """
    try:
        get_vault()
        # Vault is initialized - basic connectivity is validated
    except Exception as e:
        raise RuntimeError("Failed to connect to vault - aborting startup") from e


def validate_db_connectivity(get_db: Callable[[], "MongoConnector"]) -> None:
    """Validate database connection at startup.

    Args:
        get_db: Callable that returns MongoConnector instance

    Raises:
        RuntimeError: If database connection fails
    """
    try:
        db = get_db()
        if db.client is not None:
            db.client.admin.command("ping")
        else:
            raise RuntimeError("MongoDB client is None")
    except Exception as e:
        raise RuntimeError("Failed to connect to MongoDB - aborting startup") from e


def log_pool_stats_once(db: "MongoConnector", logger: logging.Logger) -> None:
    """Log MongoDB pool statistics once.

    This is a single iteration of pool monitoring.

    Args:
        db: MongoConnector instance
        logger: Logger to use for output
    """
    try:
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


async def pool_monitor_loop(
    get_db: Callable[[], "MongoConnector"],
    interval: int | float,
    logger: logging.Logger,
) -> None:
    """Background task to periodically log MongoDB pool statistics.

    This runs indefinitely, calling log_pool_stats_once at the specified interval.

    Args:
        get_db: Callable that returns MongoConnector instance
        interval: Time in seconds between each pool stats log (int or float for testing)
        logger: Logger to use for output
    """
    while True:
        await asyncio.sleep(interval)
        db = get_db()
        log_pool_stats_once(db, logger)


@asynccontextmanager
async def create_app_lifespan(
    deps: StartupDependencies,
    logger: logging.Logger | None = None,
) -> AsyncGenerator[None, None]:
    """Create app lifespan context manager with injectable dependencies.

    Args:
        deps: Startup dependencies to use
        logger: Optional logger (defaults to "deployment" logger)

    Yields:
        None during app runtime

    Raises:
        RuntimeError: If startup validation fails
    """
    if logger is None:
        logger = logging.getLogger("deployment")

    async with AsyncExitStack() as stack:
        # === STARTUP VALIDATION ===
        logger.info("Starting application - validating dependencies...")

        # 1. Validate vault connectivity
        try:
            validate_vault_connectivity(deps.get_vault)
            logger.info("✓ Vault connection established")
        except RuntimeError:
            logger.critical("✗ Vault connection failed")
            raise

        # 2. Validate database connectivity
        try:
            validate_db_connectivity(deps.get_db)
            logger.info("✓ MongoDB connection established")
        except RuntimeError:
            logger.critical("✗ MongoDB connection failed")
            raise

        # 3. Run migrations and other initialization
        await stack.enter_async_context(deps.did_service_lifespan())

        # 4. Start background pool monitoring task
        config = deps.get_config()
        pool_monitor_interval = config.mongo_pool.pool_monitor_interval_s
        pool_monitor = asyncio.create_task(
            pool_monitor_loop(deps.get_db, pool_monitor_interval, logger)
        )
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
