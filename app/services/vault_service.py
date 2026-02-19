"""High-level vault service wrapping the vault client protocol.

This module provides VaultService - a high-level abstraction for vault operations
that wraps a VaultClientProtocol implementation. It provides business-logic-level
operations for managing secrets, division signing keys, and public keys.
"""

from contextlib import contextmanager
from datetime import datetime
from typing import Generator, List, Optional, Any
import gc
import logging
import secrets as python_secrets

from nacl.signing import SigningKey

from app.services.vault_protocol import VaultClientProtocol


logger = logging.getLogger("vault_service")


# =============================================================================
# Exceptions
# =============================================================================

class SecretNotFoundError(Exception):
    """Raised when a secret cannot be found in vault."""

    def __init__(self, path: str, mount_point: str):
        self.path = path
        self.mount_point = mount_point
        super().__init__(f"Secret not found: {mount_point}/{path}")


class DivisionPublicKeysNotFoundError(Exception):
    """Raised when public keys cannot be found for a division."""

    def __init__(self, division: str):
        self.division = division
        super().__init__(f"Public keys not found for division '{division}'")


class SigningKeyNotFoundError(Exception):
    """Raised when a signing key cannot be found."""

    def __init__(self, division: str, fragment: str):
        self.division = division
        self.fragment = fragment
        super().__init__(f"Signing key '{fragment}' not found for division '{division}'")


# =============================================================================
# VaultService
# =============================================================================

class VaultService:
    """High-level service for vault operations.

    This class provides business-logic-level operations for:
    - Reading/writing secrets
    - Managing division signing keys
    - Managing division public keys

    It wraps a VaultClientProtocol implementation, allowing different
    backends (real vault, file mock, in-memory mock) to be used
    interchangeably.

    Example usage:
        # Production
        client = HvacVaultClient(addr="https://vault:8200", token="...")
        vault_svc = VaultService(client, mount_point="secret")

        # Testing
        client = InMemoryVaultClient()
        vault_svc = VaultService(client, mount_point="secret")

        # Use the service
        keys = vault_svc.get_division_public_keys("advisory")
    """

    def __init__(self, client: VaultClientProtocol, mount_point: str):
        """Initialize the vault service.

        Args:
            client: The vault client implementation
            mount_point: Default mount point for secrets (e.g., "secret")
        """
        self._client = client
        self._mount = mount_point

    @property
    def mount_point(self) -> str:
        """Get the default mount point."""
        return self._mount

    def is_authenticated(self) -> bool:
        """Check if vault is authenticated.

        Returns:
            True if the underlying client is authenticated, False otherwise.
        """
        return self._client.is_authenticated()

    # =========================================================================
    # Basic Secret Operations
    # =========================================================================

    def fetch_secret(self, path: str) -> dict:
        """Fetch a secret from vault.

        Args:
            path: Path to the secret (relative to mount point)

        Returns:
            The secret data as a dictionary

        Raises:
            SecretNotFoundError: If the secret doesn't exist
        """
        try:
            return self._client.read_secret(self._mount, path)
        except Exception as e:
            raise SecretNotFoundError(path, self._mount) from e

    def fetch_secret_or_default(self, path: str, default: Optional[dict] = None) -> dict:
        """Fetch a secret from vault, returning a default if not found.

        Args:
            path: Path to the secret (relative to mount point)
            default: Value to return if secret not found (defaults to empty dict)

        Returns:
            The secret data or the default value
        """
        try:
            return self._client.read_secret(self._mount, path)
        except Exception:
            return default if default is not None else {}

    def write_secret(self, path: str, data: dict) -> None:
        """Write a secret to vault.

        Args:
            path: Path to the secret (relative to mount point)
            data: The secret data to write
        """
        self._client.write_secret(self._mount, path, data)

    def list_secrets(self, path: str) -> List[str]:
        """List secrets at a path.

        Args:
            path: Path to list (relative to mount point)

        Returns:
            List of secret names/paths
        """
        try:
            return self._client.list_secrets(self._mount, path)
        except Exception:
            return []

    def delete_secret(self, path: str) -> None:
        """Delete a secret from vault.

        Args:
            path: Path to the secret (relative to mount point)
        """
        self._client.delete_secret(self._mount, path)

    # =========================================================================
    # Division Public Key Operations
    # =========================================================================

    def get_division_public_keys(self, division: str) -> List[dict]:
        """Get all public keys for a division.

        Fetches from path: divisions/{division}/public_keys

        The stored document should have the structure:
        {
            "keys": [
                {"fragment": "key20260204", "public_key_multibase": "z6Mk..."},
                {"fragment": "key20260205", "public_key_multibase": "z6Mk..."}
            ]
        }

        Args:
            division: The division identifier

        Returns:
            List of key info dicts, each containing 'fragment' and 'public_key_multibase'

        Raises:
            DivisionPublicKeysNotFoundError: If no keys exist for the division
        """
        path = f"divisions/{division}/public_keys"
        try:
            data = self.fetch_secret(path)
            keys = data.get("keys", [])
            if not keys:
                raise DivisionPublicKeysNotFoundError(division)
            return keys
        except SecretNotFoundError:
            raise DivisionPublicKeysNotFoundError(division)

    # =========================================================================
    # Division Signing Key Operations
    # =========================================================================

    def list_division_signing_key_fragments(self, division: str) -> List[str]:
        """List available signing key fragments for a division.

        Lists keys at path: divisions/{division}/signing_keys/

        Args:
            division: The division identifier

        Returns:
            List of fragment identifiers (e.g., ["key20260204", "key20260205"])
        """
        path = f"divisions/{division}/signing_keys"
        return self.list_secrets(path)

    def get_signing_key_hex(self, division: str, fragment: str) -> str:
        """Get a signing key's hex-encoded secret.

        Fetches from path: divisions/{division}/signing_keys/{fragment}

        Args:
            division: The division identifier
            fragment: The key fragment identifier

        Returns:
            Hex-encoded 32-byte secret key

        Raises:
            SigningKeyNotFoundError: If the key doesn't exist
        """
        path = f"divisions/{division}/signing_keys/{fragment}"
        try:
            data = self.fetch_secret(path)
            secret_hex = data.get("secret_key_hex")
            if not secret_hex:
                raise SigningKeyNotFoundError(division, fragment)
            return secret_hex
        except SecretNotFoundError:
            raise SigningKeyNotFoundError(division, fragment)

    @contextmanager
    def signing_key_context(
        self, division: str, fragment: str
    ) -> Generator[tuple[SigningKey, str], None, None]:
        """Context manager for secure signing key usage.

        Fetches the key from vault, yields it for use, then securely clears
        the key material from memory using sodium_memzero.

        Usage:
            with vault_svc.signing_key_context("advisory", "key20260204") as (signing_key, frag):
                signature = sign_vc(vc, signing_key, f"did:example:{frag}")
            # Key material is securely cleared here

        Args:
            division: The division identifier
            fragment: The key fragment identifier

        Yields:
            Tuple of (SigningKey, fragment)

        Raises:
            SigningKeyNotFoundError: If the key doesn't exist
        """
        # Import here to avoid circular dependency
        from app.did_utils.eddsa import sodium_memzero, secure_clear_signing_key

        key_bytes: bytearray | None = None
        signing_key: SigningKey | None = None

        try:
            secret_hex = self.get_signing_key_hex(division, fragment)

            try:
                key_bytes = bytearray.fromhex(secret_hex)
            except ValueError:
                raise SigningKeyNotFoundError(division, fragment)

            # Clear our reference to the hex string
            del secret_hex

            # Validate key length (Ed25519 seed is 32 bytes)
            if len(key_bytes) != 32:
                raise SigningKeyNotFoundError(division, fragment)

            # Create signing key from bytes
            signing_key = SigningKey(bytes(key_bytes))

            # Zero the intermediate bytearray
            sodium_memzero(key_bytes)
            key_bytes = None

            yield signing_key, fragment

        finally:
            # Securely clear the signing key material
            if signing_key is not None:
                secure_clear_signing_key(signing_key, trigger_gc=False)

            # Ensure key_bytes is cleared (triggered on exception cases)
            if key_bytes is not None:
                try:
                    sodium_memzero(key_bytes)
                except Exception:
                    pass

            # Force garbage collection
            gc.collect()

    def ensure_division_signing_key(self, division: str) -> str:
        """Ensure at least one signing key exists for a division.

        If no signing key exists, generates a new Ed25519 keypair and stores:
        - Private key at: divisions/{division}/signing_keys/{fragment}
        - Public key appended to: divisions/{division}/public_keys

        This function is idempotent - if keys already exist, it returns the
        latest fragment without making changes.

        Args:
            division: The division identifier

        Returns:
            The fragment identifier of an existing or newly created key

        Note:
            The newly generated private key is securely cleared from memory
            after being stored in vault.
        """
        # Import here to avoid circular dependency
        from app.did_utils.eddsa import get_public_key_multibase, sodium_memzero

        # Check if any signing keys already exist
        existing_fragments = self.list_division_signing_key_fragments(division)
        if existing_fragments:
            logger.info(f"Division '{division}' already has {len(existing_fragments)} signing key(s)")
            return sorted(existing_fragments)[-1]  # Return the latest fragment

        # Generate a new key fragment based on current date
        fragment = f"key{datetime.utcnow().strftime('%Y%m%d')}"

        # Generate a cryptographically secure random 32-byte seed
        seed_bytes = bytearray(python_secrets.token_bytes(32))
        secret_key_hex = seed_bytes.hex()

        try:
            # Create SigningKey to compute public key
            signing_key = SigningKey(bytes(seed_bytes))
            public_key_multibase = get_public_key_multibase(signing_key)

            # Store the private key in vault
            private_key_path = f"divisions/{division}/signing_keys/{fragment}"
            self.write_secret(private_key_path, {"secret_key_hex": secret_key_hex})
            logger.info(f"Created signing key for division '{division}' at {private_key_path}")

            # Store/update the public keys list
            public_keys_path = f"divisions/{division}/public_keys"
            try:
                existing_public_keys = self.fetch_secret(public_keys_path)
                keys_list = existing_public_keys.get("keys", [])
            except SecretNotFoundError:
                keys_list = []

            keys_list.append({
                "fragment": fragment,
                "public_key_multibase": public_key_multibase,
            })

            self.write_secret(public_keys_path, {"keys": keys_list})
            logger.info(f"Updated public keys for division '{division}' with fragment '{fragment}'")

            return fragment

        finally:
            # Securely clear the seed bytes from memory
            sodium_memzero(seed_bytes)
            # Clear the hex string reference (best effort - strings are immutable)
            del secret_key_hex
            gc.collect()

    def get_active_signing_key_fragment(self, division: str) -> str:
        """Get the fragment identifier of the active (latest) signing key.

        The active key is determined by sorting available fragments
        alphabetically and returning the last one (latest by convention).

        Args:
            division: The division identifier

        Returns:
            The fragment identifier of the active signing key

        Raises:
            SigningKeyNotFoundError: If no signing keys exist for the division
        """
        fragments = self.list_division_signing_key_fragments(division)
        if not fragments:
            raise SigningKeyNotFoundError(division, "<none>")
        # Return the latest fragment (by convention, sorted alphabetically)
        return sorted(fragments)[-1]
