"""Reusable dependencies for FastAPI routes."""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Header, HTTPException

from app.config import get_config, reset_config_cache
from app.constants import EXAMPLE_API_TOKEN

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from app.database import MongoConnector
    from app.services.did_service import DIDService
    from app.services.vault_protocol import VaultClientProtocol
    from app.services.vault_service import VaultService

logger = logging.getLogger("did_vault_api_sut")


async def verify_epdw_token(
    x_api_token: str = Header(
        ...,
        description="EPDW API access token required for authentication.",
        openapi_examples={"normal":{"value":EXAMPLE_API_TOKEN}},
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
        openapi_examples={"normal":{"value":EXAMPLE_API_TOKEN}},
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


async def verify_didcheck_token(
    x_api_token: str = Header(
        ...,
        description="DIDCheck API access token required for authentication.",
        openapi_examples={"normal":{"value":EXAMPLE_API_TOKEN}},
        alias="X-API-Token",
    )
) -> str:
    """
    Dependency that validates the DIDCheck API token from the request header.

    Uses lazy config loading to allow test overrides.
    In development, if DIDCHECK_ACCESS_TOKEN is not set, token validation is bypassed.

    Raises:
        HTTPException: 401 if token is invalid (when token is configured)

    Returns:
        The validated token string
    """
    config = get_config()
    expected_token = config.tokens.didcheck_access_token

    # Allow bypass in development if token not configured
    if not expected_token:
        return x_api_token

    if not secrets.compare_digest(x_api_token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid DIDCheck token")
    return x_api_token

async def verify_demodiv_token(
    x_api_token: str = Header(
        ...,
        description="Demo division API access token required for authentication.",
        openapi_examples={"normal":{"value":EXAMPLE_API_TOKEN}},
        alias="X-API-Token",
    )
) -> str:
    """
    Dependency that validates the Demo division API token from the request header.

    Uses lazy config loading to allow test overrides.
    In development, if DEMODIV_ACCESS_TOKEN is not set, token validation is bypassed.

    Raises:
        HTTPException: 401 if token is invalid (when token is configured)

    Returns:
        The validated token string
    """
    config = get_config()
    expected_token = config.tokens.didcheck_access_token

    # Allow bypass in development if token not configured
    if not expected_token:
        return x_api_token

    if not secrets.compare_digest(x_api_token, expected_token):
        raise HTTPException(status_code=401, detail="Invalid DIDCheck token")
    return x_api_token



# EPDW-specific token dependency
EPDWTokenDep = Annotated[str, Depends(verify_epdw_token)]

# Advisory-specific token dependency
AdvisoryTokenDep = Annotated[str, Depends(verify_advisory_token)]

# DIDCheck-specific token dependency
DIDCheckTokenDep = Annotated[str, Depends(verify_didcheck_token)]

# Demodiv-specific token dependency
DemoDivTokenDep = Annotated[str, Depends(verify_demodiv_token)]


# Response documentation for token dependencies.
APITokenDep401Response = {401: {"description": "Invalid or missing API token"}}


# =============================================================================
# Vault Client Factory
# =============================================================================

_vault_client: VaultClientProtocol | None = None
_vault_client_initialized: bool = False


def _create_vault_client() -> VaultClientProtocol:
    """Create a vault client based on configuration.

    Returns:
        Either an HvacVaultClient, MockVaultClient, or raises if config is invalid.
    """
    config = get_config()

    # Check if we should use the local file-based mock
    if config.vault.local_mock_path:
        from app.services.vault_mock import MockVaultClient

        logger.info(f"[INFO] Using local mock Vault at: {config.vault.local_mock_path}")
        return MockVaultClient(
            root_dir=config.vault.local_mock_path,
            default_mount=config.vault.mount,
        )

    # Use real vault via hvac
    from app.services.vault_clients import HvacVaultClient

    client = HvacVaultClient(addr=config.vault.addr, token=config.vault.token)
    if client.is_authenticated():
        logger.info(f"[INFO] Vault connected: {config.vault.addr}")
    else:
        logger.warning(f"[WARN] Vault authentication failed: {config.vault.addr}")
    return client


def get_vault_client() -> VaultClientProtocol:
    """Get the vault client, initializing it lazily if needed.

    Returns:
        The vault client (HvacVaultClient or MockVaultClient)
    """
    global _vault_client, _vault_client_initialized
    if not _vault_client_initialized:
        _vault_client = _create_vault_client()
        _vault_client_initialized = True
    return _vault_client  # type: ignore


def reset_vault_client() -> None:
    """Reset the vault client (for testing)."""
    global _vault_client, _vault_client_initialized
    _vault_client = None
    _vault_client_initialized = False


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
        from app.services.vault_service import VaultService

        client = get_vault_client()
        config = get_config()
        _vault_service = VaultService(client, mount_point=config.vault.mount)
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
        with suppress(Exception):
            _db_connector.close_connection()
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

_did_service: DIDService | None = None
_did_service_initialized: bool = False


def get_did_service() -> DIDService:
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


def set_did_service_dependency(did_svc: DIDService) -> None:
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
    reset_vault_client()
    reset_vault_dependency()
    reset_db_dependency()
    reset_did_service_dependency()
    reset_config_cache()
