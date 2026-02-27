"""Vault client implementations.

This module provides concrete implementations of VaultClientProtocol:
- HvacVaultClient: Real HashiCorp Vault via hvac library
- InMemoryVaultClient: In-memory mock for unit tests
"""

from typing import Any

import hvac
import hvac.exceptions


class HvacVaultClient:
    """Real vault client using hvac library.

    This implementation wraps the hvac library and provides a simplified
    interface for KV v2 operations.
    """

    def __init__(self, addr: str, token: str):
        """Initialize the hvac vault client.

        Args:
            addr: Vault server address (e.g., "https://vault.example.com:8200")
            token: Vault authentication token
        """
        self._client = hvac.Client(url=addr, token=token)

    def is_authenticated(self) -> bool:
        """Check if the client is authenticated with vault."""
        try:
            return self._client.is_authenticated()
        except Exception:
            return False

    def read_secret(self, mount_point: str, path: str) -> dict[str, Any]:
        """Read a secret from vault KV v2.

        Args:
            mount_point: The mount point (e.g., "secret")
            path: Path to the secret

        Returns:
            The secret data as a dictionary

        Raises:
            hvac.exceptions.InvalidPath: If the secret doesn't exist
        """
        result = self._client.secrets.kv.v2.read_secret_version(
            mount_point=mount_point, path=path
        )
        return result.get("data", {}).get("data", {})

    def write_secret(self, mount_point: str, path: str, data: dict[str, Any]) -> None:
        """Write a secret to vault KV v2.

        Args:
            mount_point: The mount point
            path: Path to the secret
            data: The secret data to write
        """
        self._client.secrets.kv.v2.create_or_update_secret(
            mount_point=mount_point, path=path, secret=data
        )

    def list_secrets(self, mount_point: str, path: str) -> list[str]:
        """List secrets at a path in vault KV v2.

        Args:
            mount_point: The mount point
            path: Path to list

        Returns:
            List of secret names/paths
        """
        result = self._client.secrets.kv.v2.list_secrets(
            mount_point=mount_point, path=path
        )
        return result.get("data", {}).get("keys", [])

    def delete_secret(self, mount_point: str, path: str) -> None:
        """Delete a secret and all its versions from vault KV v2.

        Args:
            mount_point: The mount point
            path: Path to the secret
        """
        self._client.secrets.kv.v2.delete_metadata_and_all_versions(
            mount_point=mount_point, path=path
        )


class InMemoryVaultClient:
    """In-memory vault client for unit testing.

    This implementation stores secrets in a dictionary, providing
    a fast, isolated vault mock for unit tests without filesystem
    or network dependencies.
    """

    def __init__(self, initial_secrets: dict[str, dict[str, Any]] | None = None):
        """Initialize with optional pre-populated secrets.

        Args:
            initial_secrets: Dict mapping "mount/path" to secret data.
                Example: {"secret/mongo": {"connection_string": "..."}}
        """
        self._secrets: dict[str, dict[str, Any]] = initial_secrets.copy() if initial_secrets else {}
        self._authenticated = True

    def set_authenticated(self, value: bool) -> None:
        """Control authentication state for testing.

        Args:
            value: Whether the client should report as authenticated
        """
        self._authenticated = value

    def is_authenticated(self) -> bool:
        """Check if the mock client is authenticated."""
        return self._authenticated

    def _key(self, mount_point: str, path: str) -> str:
        """Build the internal storage key from mount point and path."""
        return f"{mount_point}/{path}"

    def read_secret(self, mount_point: str, path: str) -> dict[str, Any]:
        """Read a secret from in-memory storage.

        Args:
            mount_point: The mount point
            path: Path to the secret

        Returns:
            The secret data as a dictionary

        Raises:
            KeyError: If the secret doesn't exist
        """
        key = self._key(mount_point, path)
        if key not in self._secrets:
            raise KeyError(f"Secret not found: {key}")
        return self._secrets[key].copy()

    def write_secret(self, mount_point: str, path: str, data: dict[str, Any]) -> None:
        """Write a secret to in-memory storage.

        Args:
            mount_point: The mount point
            path: Path to the secret
            data: The secret data to write
        """
        key = self._key(mount_point, path)
        self._secrets[key] = data.copy()

    def list_secrets(self, mount_point: str, path: str) -> list[str]:
        """List secrets at a path in in-memory storage.

        This mimics vault's list behavior:
        - Returns immediate children of the path
        - Directories are indicated by trailing "/"

        Args:
            mount_point: The mount point
            path: Path to list

        Returns:
            List of secret names/paths
        """
        prefix = self._key(mount_point, path)
        if not prefix.endswith("/"):
            prefix += "/"

        results = set()
        for key in self._secrets:
            if key.startswith(prefix):
                remainder = key[len(prefix):]
                if "/" in remainder:
                    # It's a nested path, return the first component with "/"
                    results.add(remainder.split("/")[0] + "/")
                else:
                    # It's a direct child
                    results.add(remainder)
        return sorted(results)

    def delete_secret(self, mount_point: str, path: str) -> None:
        """Delete a secret from in-memory storage.

        Args:
            mount_point: The mount point
            path: Path to the secret
        """
        key = self._key(mount_point, path)
        self._secrets.pop(key, None)

    def clear(self) -> None:
        """Clear all secrets from storage. Useful for test cleanup."""
        self._secrets.clear()

    def get_all_secrets(self) -> dict[str, dict[str, Any]]:
        """Get all secrets in storage. Useful for test assertions.

        Returns:
            Copy of the internal secrets dictionary
        """
        return self._secrets.copy()
