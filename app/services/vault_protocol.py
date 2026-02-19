"""Protocol definitions for vault operations.

This module defines the abstract interface for vault client implementations,
enabling dependency injection and testability.
"""

from typing import Protocol, List, Any, Dict


class VaultClientProtocol(Protocol):
    """Protocol for vault client implementations.

    Implementations:
    - HvacVaultClient: Real HashiCorp Vault via hvac library
    - MockVaultClient: File-based mock (existing vault_mock.py)
    - InMemoryVaultClient: In-memory mock for unit tests

    All implementations must provide these methods to be compatible
    with VaultService.
    """

    def is_authenticated(self) -> bool:
        """Check if the client is authenticated.

        Returns:
            True if authenticated, False otherwise.
        """
        ...

    def read_secret(self, mount_point: str, path: str) -> Dict[str, Any]:
        """Read a secret from vault.

        Args:
            mount_point: The mount point (e.g., "secret")
            path: Path to the secret

        Returns:
            The secret data as a dictionary

        Raises:
            KeyError or similar: If the secret doesn't exist
        """
        ...

    def write_secret(self, mount_point: str, path: str, data: Dict[str, Any]) -> None:
        """Write a secret to vault.

        Args:
            mount_point: The mount point
            path: Path to the secret
            data: The secret data to write
        """
        ...

    def list_secrets(self, mount_point: str, path: str) -> List[str]:
        """List secrets at a path.

        Args:
            mount_point: The mount point
            path: Path to list

        Returns:
            List of secret names/paths
        """
        ...

    def delete_secret(self, mount_point: str, path: str) -> None:
        """Delete a secret.

        Args:
            mount_point: The mount point
            path: Path to the secret
        """
        ...
