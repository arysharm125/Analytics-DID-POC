"""Reusable dependencies for FastAPI routes."""

from __future__ import annotations
from contextlib import asynccontextmanager
import secrets
from typing import Annotated, TYPE_CHECKING, AsyncGenerator

from fastapi import Depends, Header, HTTPException

from app.config import get_config, reset_config_cache
from app.constants import EXAMPLE_API_TOKEN

if TYPE_CHECKING:
    from app.database import MongoConnector
    from app.services.vault_service import VaultService
    from app.services.did_service import DIDService


async def verify_epdw_token(
    x_api_token: str = Header(
        ...,
        description="EPDW API access token required for authentication.",
        example=EXAMPLE_API_TOKEN,
        alias="X-API-Token",
    )
) -> str:
    """
    Dependency that validates the EPDW API token from the request header.

    Uses lazy config loading to allow test overrides.

    Raises:
        HTTPException: 401 if token is missing or invalid

    Returns:
        The validated token string
    """
    config = get_config()
    if not secrets.compare_digest(x_api_token, config.tokens.epdw_access_token):
        raise HTTPException(status_code=401, detail="Invalid EPDW token")
    return x_api_token


async def verify_advisory_token(
    x_api_token: str = Header(
        ...,
        description="Advisory API access token required for authentication.",
        example=EXAMPLE_API_TOKEN,
        alias="X-API-Token",
    )
) -> str:
    """
    Dependency that validates the Advisory API token from the request header.

    Uses lazy config loading to allow test overrides.

    Raises:
        HTTPException: 401 if token is missing or invalid

    Returns:
        The validated token string
    """
    config = get_config()
    if not secrets.compare_digest(x_api_token, config.tokens.advisory_access_token):
        raise HTTPException(status_code=401, detail="Invalid Advisory token")
    return x_api_token


# EPDW-specific token dependency
EPDWTokenDep = Annotated[str, Depends(verify_epdw_token)]

# Advisory-specific token dependency
AdvisoryTokenDep = Annotated[str, Depends(verify_advisory_token)]

# Response documentation for token dependencies.
APITokenDep401Response = {401: {"description": "Invalid or missing API token"}}


# =============================================================================
# Vault Service Dependency
# =============================================================================

_vault_service: VaultService | None = None
_vault_service_initialized: bool = False


def get_vault() -> VaultService:
    """FastAPI dependency to get VaultService instance.

    The VaultService is lazily initialized on first access and cached
    for subsequent requests. Uses configuration to determine whether
    to use real vault or file-based mock.

    Returns:
        VaultService instance

    Example:
        @router.get("/example")
        def example(vault: VaultServiceDep):
            secret = vault.fetch_secret("my-secret")
    """
    global _vault_service, _vault_service_initialized

    if not _vault_service_initialized:
        from app.services.vault import get_vault_service
        _vault_service = get_vault_service()
        _vault_service_initialized = True

    return _vault_service  # type: ignore


def reset_vault_dependency() -> None:
    """Reset the vault dependency cache.

    Use this in tests to clear the cached VaultService.
    """
    global _vault_service, _vault_service_initialized
    _vault_service = None
    _vault_service_initialized = False


def set_vault_dependency(vault_svc: VaultService) -> None:
    """Set the vault dependency directly.

    Use this in tests to inject a mock VaultService.

    Args:
        vault_svc: The VaultService instance to use
    """
    global _vault_service, _vault_service_initialized
    _vault_service = vault_svc
    _vault_service_initialized = True


# Type alias for VaultService dependency injection
VaultServiceDep = Annotated["VaultService", Depends(get_vault)]


# =============================================================================
# Database Dependency
# =============================================================================

_db_connector: MongoConnector | None = None
_db_connector_initialized: bool = False


def get_db() -> MongoConnector:
    """FastAPI dependency to get MongoConnector instance.

    The MongoConnector is lazily initialized on first access and cached
    for subsequent requests. In production, it reads connection config
    from vault.

    Returns:
        MongoConnector instance

    Example:
        @router.get("/example")
        def example(db: MongoConnectorDep):
            collection = db.get_collection("my_collection")
    """
    global _db_connector, _db_connector_initialized

    if not _db_connector_initialized:
        from app.database import MongoConnector
        vault_svc = get_vault()
        _db_connector = MongoConnector.from_vault_service(vault_svc)
        _db_connector_initialized = True

    return _db_connector  # type: ignore


def reset_db_dependency() -> None:
    """Reset the database dependency cache.

    Use this in tests to clear the cached MongoConnector.
    """
    global _db_connector, _db_connector_initialized
    if _db_connector is not None and _db_connector.client is not None:
        try:
            _db_connector.close_connection()
        except Exception:
            pass
    _db_connector = None
    _db_connector_initialized = False


def set_db_dependency(db: MongoConnector) -> None:
    """Set the database dependency directly.

    Use this in tests to inject a mock or test database.

    Args:
        db: The MongoConnector instance to use
    """
    global _db_connector, _db_connector_initialized
    _db_connector = db
    _db_connector_initialized = True


# Type alias for MongoConnector dependency injection
MongoConnectorDep = Annotated["MongoConnector", Depends(get_db)]


# =============================================================================
# DIDService Dependency
# =============================================================================

_did_service: "DIDService | None" = None
_did_service_initialized: bool = False


def get_did_service() -> "DIDService":
    """FastAPI dependency to get DIDService instance.

    The DIDService is lazily initialized on first access and cached
    for subsequent requests. It uses the cached VaultService and
    MongoConnector instances.

    Returns:
        DIDService instance

    Example:
        @router.get("/example")
        def example(did_svc: DIDServiceDep):
            artefact = did_svc.find_by_external_uid(uid)
    """
    global _did_service, _did_service_initialized

    if not _did_service_initialized:
        from app.services.did_service import DIDService
        db = get_db()
        vault_svc = get_vault()
        _did_service = DIDService(db=db, vault_svc=vault_svc)
        _did_service_initialized = True

    return _did_service  # type: ignore


def reset_did_service_dependency() -> None:
    """Reset the DIDService dependency cache.

    Use this in tests to clear the cached DIDService.
    """
    global _did_service, _did_service_initialized
    _did_service = None
    _did_service_initialized = False


def set_did_service_dependency(did_svc: "DIDService") -> None:
    """Set the DIDService dependency directly.

    Use this in tests to inject a mock or test DIDService.

    Args:
        did_svc: The DIDService instance to use
    """
    global _did_service, _did_service_initialized
    _did_service = did_svc
    _did_service_initialized = True


# Type alias for DIDService dependency injection
DIDServiceDep = Annotated["DIDService", Depends(get_did_service)]


@asynccontextmanager
async def did_service_lifespan() -> AsyncGenerator[None, None]:
    """Control lifespan of global DIDService instance."""

    # Initialize the DIDService (runs migrations, ensures signing keys)
    get_did_service()
    try:
        yield
    finally:
        pass  # No shutdown procedure yet.

# =============================================================================
# Test Utilities
# =============================================================================

def reset_all_dependencies() -> None:
    """Reset all cached dependencies.

    Use this in tests to clear all cached services (vault, database, and DIDService).
    Should be called in test teardown to ensure clean state.
    """
    reset_vault_dependency()
    reset_db_dependency()
    reset_did_service_dependency()
    reset_config_cache()
