"""Vault integration module with lazy initialization and abstraction support.

This module provides:
1. Lazy-initialized vault client (real or mock based on config)
2. Lazy-initialized VaultService wrapping the client
3. Backward-compatible module-level functions that delegate to VaultService
4. Division signing key operations

The lazy initialization pattern ensures no vault connections are made at import
time, enabling tests to override configuration before any connections occur.
"""

import logging
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from nacl.signing import SigningKey

from app.config import get_config
from app.services.vault_protocol import VaultClientProtocol
from app.services.vault_service import (
    DivisionPublicKeysNotFoundError,
    SecretNotFoundError,
    SigningKeyNotFoundError,
    VaultService,
)

# Re-export exceptions for backward compatibility
__all__ = [
    # Exceptions
    "InvalidPathException",
    "SecretNotFoundError",
    "DivisionPublicKeysNotFoundError",
    "SigningKeyNotFoundError",
    # Service access
    "get_vault_service",
    "reset_vault_service",
    # Backward-compatible functions
    "get_vault_client",
    "reset_vault_client",
    "vault_read",
    "vault_read_dict",
    "vault_read_dict_or_raise",
    "vault_write",
    "vault_list",
    "vault_store_secret",
    "vault_fetch_secret",
    "vault_delete_metadata_and_all_versions",
    "vault_is_authenticated",
    "vault_get_division_public_keys",
    "vault_list_division_signing_key_fragments",
    "vault_signing_key_context",
    "vault_ensure_division_signing_key",
]


logger = logging.getLogger("did_vault_api_sut")


# =============================================================================
# Exceptions (backward compatibility)
# =============================================================================

class InvalidPathException(Exception):
    """Raised when trying to read a path that does not exist."""
    path: str
    mount_point: str

    def __init__(self, path: str, mount_point: str) -> None:
        super().__init__(f"Unable to read ${mount_point}/${path}")
        self.path = path
        self.mount_point = mount_point


# =============================================================================
# Lazy Vault Client Initialization
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
    # Also reset the vault service
    reset_vault_service()


# =============================================================================
# Lazy VaultService Initialization
# =============================================================================

_vault_service: VaultService | None = None
_vault_service_initialized: bool = False


def get_vault_service() -> VaultService:
    """Get the VaultService instance, initializing it lazily if needed.

    This is the preferred way to access vault operations in new code.
    The service wraps the vault client and provides high-level operations.

    Returns:
        VaultService instance
    """
    global _vault_service, _vault_service_initialized
    if not _vault_service_initialized:
        client = get_vault_client()
        config = get_config()
        _vault_service = VaultService(client, mount_point=config.vault.mount)
        _vault_service_initialized = True
    return _vault_service  # type: ignore


def reset_vault_service() -> None:
    """Reset the VaultService (for testing)."""
    global _vault_service, _vault_service_initialized
    _vault_service = None
    _vault_service_initialized = False


def set_vault_service(service: VaultService) -> None:
    """Set the VaultService instance directly (for testing).

    Args:
        service: The VaultService instance to use
    """
    global _vault_service, _vault_service_initialized
    _vault_service = service
    _vault_service_initialized = True


# =============================================================================
# Backward-Compatible Module Functions
# =============================================================================

def get_vault_config() -> tuple[str, str, str]:
    """Fetches Vault address, token, and mount path from lazy-loaded config."""
    config = get_config()
    return config.vault.addr, config.vault.token, config.vault.mount


def vault_write(mount_point: str, path: str, secret: Any) -> None:
    """
    Safe Vault KV writer:
    - Ensures KV v2 always receives a dict
    - Auto-wraps lists/strings into {"value": ...}
    - Prevents 'expected a map, got string' errors
    """
    # Always wrap non-dicts
    if not isinstance(secret, dict):
        secret = {"value": secret}

    client = get_vault_client()
    client.write_secret(mount_point, path, secret)


def vault_read(mount_point: str, path: str) -> list[Any]:
    """
    Always returns clean value:
    - If stored as {"chain": [...] } → returns [...]
    - If missing → returns []
    """
    client = get_vault_client()
    try:
        data = client.read_secret(mount_point, path)

        # Normalize chain
        if isinstance(data, dict) and "chain" in data:
            return data["chain"]

        # If already a list
        if isinstance(data, list):
            return data

        return []
    except Exception:
        return []


def vault_read_dict_or_raise(mount_point: str, path: str) -> dict:
    """
    Reads a secret dict and returns its data. This raises an exception
    if the secret data does not exist.
    """
    client = get_vault_client()
    try:
        return client.read_secret(mount_point, path)
    except Exception:
        raise InvalidPathException(path=path, mount_point=mount_point)


def vault_read_dict(mount_point: str, path: str) -> dict:
    """
    Reads a secret dict, then returns data. This returns an empty dict
    if the data does not exist.
    """
    try:
        return vault_read_dict_or_raise(mount_point=mount_point, path=path)
    except Exception as ex:
        logger.warning(f"Unable to read secret ${mount_point}/${path}: ${ex}")
        return {}


def vault_list(mount_point: str, path: str) -> list[str]:
    """List secrets at a given path."""
    client = get_vault_client()
    return client.list_secrets(mount_point, path)


def vault_store_secret(path: str, data: dict, lifespan_minutes: int = 10) -> str:
    """Store a secret with automatic expiration."""
    config = get_config()
    expires_at = (datetime.utcnow() + timedelta(minutes=lifespan_minutes)).isoformat()
    vault_write(config.vault.mount, path, {**data, "expires_at": expires_at})

    def delayed_delete() -> None:
        time.sleep(lifespan_minutes * 60)
        try:
            vault_delete_metadata_and_all_versions(config.vault.mount, path)
        except Exception as e:
            logger.exception("Auto-delete failed for %s: %s", path, e)

    threading.Thread(target=delayed_delete, daemon=True).start()
    return expires_at


def vault_fetch_secret(path: str) -> dict:
    """Fetch a secret from the default mount point."""
    svc = get_vault_service()
    return svc.fetch_secret_or_default(path, default={})


def vault_delete_metadata_and_all_versions(mount_point: str, path: str) -> None:
    """Delete a secret and all its versions."""
    client = get_vault_client()
    client.delete_secret(mount_point, path)


def vault_is_authenticated() -> bool:
    """Returns true if the vault client is initialized and authenticated."""
    try:
        client = get_vault_client()
        return client.is_authenticated()
    except Exception:
        return False


# =============================================================================
# Division Signing Key Operations (delegated to VaultService)
# =============================================================================

def vault_get_division_public_keys(
    division: str,
    mount_point: str | None = None,
) -> list[dict]:
    svc = get_vault_service()
    return svc.get_division_public_keys(division)


def vault_list_division_signing_key_fragments(
    division: str,
    mount_point: str | None = None,
) -> list[str]:
    svc = get_vault_service()
    return svc.list_division_signing_key_fragments(division)


@contextmanager
def vault_signing_key_context(
    division: str,
    fragment: str,
    mount_point: str | None = None,
) -> Generator[tuple[SigningKey, str], None, None]:
    svc = get_vault_service()
    with svc.signing_key_context(division, fragment) as key_and_frag:
        yield key_and_frag


def vault_ensure_division_signing_key(
    division: str,
    mount_point: str | None = None,
) -> str:
    svc = get_vault_service()
    return svc.ensure_division_signing_key(division)
