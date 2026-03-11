"""FastAPI application factory for improved testability.

This module provides a factory function to create the FastAPI app instance,
allowing for configuration and dependency injection during testing.
"""

from collections.abc import Callable

from fastapi import FastAPI, HTTPException

from app.config import get_config
from app.lifespan import StartupDependencies, create_app_lifespan
from app.middlewares import exception_handler_middleware, http_exception_handler
from app.request_id import AccessLogMiddleware, RequestIdMiddleware
from app.routers.advisory_router import router as advisory_router
from app.routers.dependencies import did_service_lifespan, get_db, get_vault
from app.routers.didcheck import app as didcheck_router
from app.routers.docs import app as docs_router
from app.routers.epdw import app as did_router
from app.routers.health import app as health_router
from app.version import VERSION


def create_app(
    lifespan: Callable | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        lifespan: Optional custom lifespan function (for testing).
                  If None, uses the default app lifespan.

    Returns:
        Configured FastAPI application instance
    """
    # Use default lifespan if not provided
    if lifespan is None:
        # Create default startup dependencies
        deps = StartupDependencies(
            get_vault=get_vault,
            get_db=get_db,
            did_service_lifespan=did_service_lifespan,
            get_config=get_config,
        )

        def default_lifespan(app):
            return create_app_lifespan(deps)

        lifespan = default_lifespan

    # Create FastAPI app
    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        version=VERSION,
    )

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

    # ==========================
    # Routers
    # ==========================
    app.include_router(did_router)
    app.include_router(advisory_router)

    # Conditionally include generic DID router based on feature flag
    include_didcheck_router = get_config().features.didcheck_router
    if include_didcheck_router:
        app.include_router(didcheck_router)

    app.include_router(health_router)
    app.include_router(docs_router)

    return app
