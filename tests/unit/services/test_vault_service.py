"""Unit tests for app/services/vault_service.py.

Tests the VaultService class methods using InMemoryVaultClient for isolation.
"""

from unittest.mock import patch

import pytest
from nacl.signing import SigningKey

from app.services.vault_clients import InMemoryVaultClient
from app.services.vault_service import (
    DivisionPublicKeysNotFoundError,
    SigningKeyNotFoundError,
    VaultService,
)


@pytest.fixture
def vault_service():
    """Create a VaultService with InMemoryVaultClient."""
    client = InMemoryVaultClient()
    return VaultService(client, mount_point="secret")


class TestGetDivisionPublicKeys:
    """Tests for get_division_public_keys method."""

    def test_get_division_public_keys_returns_keys(self, vault_service):
        """Getting public keys with valid data should return the keys list."""
        # Arrange: Write valid public keys data
        vault_service.write_secret(
            "divisions/test-division/public_keys",
            {
                "keys": [
                    {
                        "fragment": "key20260204",
                        "public_key_multibase": "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
                    },
                    {
                        "fragment": "key20260205",
                        "public_key_multibase": "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doL",
                    },
                ]
            },
        )

        # Act
        keys = vault_service.get_division_public_keys("test-division")

        # Assert
        assert len(keys) == 2
        assert keys[0]["fragment"] == "key20260204"
        assert keys[1]["fragment"] == "key20260205"
        assert "public_key_multibase" in keys[0]
        assert "public_key_multibase" in keys[1]

    def test_get_division_public_keys_empty_keys_raises(self, vault_service):
        """Getting public keys when keys list is empty should raise DivisionPublicKeysNotFoundError."""
        # Arrange: Write secret with empty keys list
        vault_service.write_secret(
            "divisions/test-division/public_keys",
            {"keys": []},
        )

        # Act & Assert
        with pytest.raises(DivisionPublicKeysNotFoundError) as exc_info:
            vault_service.get_division_public_keys("test-division")

        assert exc_info.value.division == "test-division"
        assert "test-division" in str(exc_info.value)

    def test_get_division_public_keys_not_found_raises(self, vault_service):
        """Getting public keys when secret doesn't exist should raise DivisionPublicKeysNotFoundError."""
        # Act & Assert
        with pytest.raises(DivisionPublicKeysNotFoundError) as exc_info:
            vault_service.get_division_public_keys("nonexistent-division")

        assert exc_info.value.division == "nonexistent-division"
        assert "nonexistent-division" in str(exc_info.value)

    def test_get_division_public_keys_missing_keys_field_raises(self, vault_service):
        """Getting public keys when secret exists but has no 'keys' field should raise DivisionPublicKeysNotFoundError."""
        # Arrange: Write secret without 'keys' field
        vault_service.write_secret(
            "divisions/test-division/public_keys",
            {"other_field": "value"},
        )

        # Act & Assert
        with pytest.raises(DivisionPublicKeysNotFoundError) as exc_info:
            vault_service.get_division_public_keys("test-division")

        assert exc_info.value.division == "test-division"


class TestGetSigningKeyHex:
    """Tests for get_signing_key_hex method."""

    def test_get_signing_key_hex_returns_hex_string(self, vault_service):
        """Getting signing key with valid data should return the hex string."""
        # Arrange: Write valid signing key
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": "a" * 64},  # 32 bytes as hex
        )

        # Act
        secret_hex = vault_service.get_signing_key_hex("test-division", "key20260204")

        # Assert
        assert secret_hex == "a" * 64
        assert len(secret_hex) == 64

    def test_get_signing_key_hex_not_found_raises(self, vault_service):
        """Getting signing key when secret doesn't exist should raise SigningKeyNotFoundError."""
        # Act & Assert
        with pytest.raises(SigningKeyNotFoundError) as exc_info:
            vault_service.get_signing_key_hex("test-division", "nonexistent-key")

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "nonexistent-key"
        assert "test-division" in str(exc_info.value)
        assert "nonexistent-key" in str(exc_info.value)

    def test_get_signing_key_hex_missing_field_raises(self, vault_service):
        """Getting signing key when secret exists but has no 'secret_key_hex' field should raise SigningKeyNotFoundError."""
        # Arrange: Write secret without 'secret_key_hex' field
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"other_field": "value"},
        )

        # Act & Assert
        with pytest.raises(SigningKeyNotFoundError) as exc_info:
            vault_service.get_signing_key_hex("test-division", "key20260204")

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"

    def test_get_signing_key_hex_empty_string_raises(self, vault_service):
        """Getting signing key when secret_key_hex is empty string should raise SigningKeyNotFoundError."""
        # Arrange: Write secret with empty string
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": ""},
        )

        # Act & Assert
        with pytest.raises(SigningKeyNotFoundError) as exc_info:
            vault_service.get_signing_key_hex("test-division", "key20260204")

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"

    def test_get_signing_key_hex_none_raises(self, vault_service):
        """Getting signing key when secret_key_hex is None should raise SigningKeyNotFoundError."""
        # Arrange: Write secret with None value
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": None},
        )

        # Act & Assert
        with pytest.raises(SigningKeyNotFoundError) as exc_info:
            vault_service.get_signing_key_hex("test-division", "key20260204")

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"


class TestSigningKeyContext:
    """Tests for signing_key_context context manager."""

    def test_signing_key_context_yields_signing_key(self, vault_service):
        """Context manager should yield a valid SigningKey and fragment."""
        # Arrange: Write valid 32-byte signing key (64 hex chars)
        import secrets

        secret_bytes = secrets.token_bytes(32)
        secret_hex = secret_bytes.hex()

        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": secret_hex},
        )

        # Act & Assert
        with vault_service.signing_key_context("test-division", "key20260204") as (signing_key, fragment):
            assert isinstance(signing_key, SigningKey)
            assert fragment == "key20260204"
            # Verify the signing key is usable
            test_message = b"test message"
            signature = signing_key.sign(test_message)
            assert signature is not None

    def test_signing_key_context_invalid_hex_raises(self, vault_service):
        """Context manager with invalid hex should raise SigningKeyNotFoundError."""
        # Arrange: Write invalid hex string
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": "not-valid-hex"},
        )

        # Act & Assert
        with (
            pytest.raises(SigningKeyNotFoundError) as exc_info,
            vault_service.signing_key_context("test-division", "key20260204"),
        ):
            pass  # Should not reach here

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"

    def test_signing_key_context_invalid_length_raises(self, vault_service):
        """Context manager with wrong key length should raise SigningKeyNotFoundError."""
        # Arrange: Write hex string of wrong length (16 bytes instead of 32)
        import secrets

        wrong_length_bytes = secrets.token_bytes(16)
        wrong_hex = wrong_length_bytes.hex()

        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": wrong_hex},
        )

        # Act & Assert
        with (
            pytest.raises(SigningKeyNotFoundError) as exc_info,
            vault_service.signing_key_context("test-division", "key20260204"),
        ):
            pass  # Should not reach here

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"

    def test_signing_key_context_not_found_raises(self, vault_service):
        """Context manager when secret doesn't exist should raise SigningKeyNotFoundError."""
        # Act & Assert
        with (
            pytest.raises(SigningKeyNotFoundError) as exc_info,
            vault_service.signing_key_context("test-division", "nonexistent-key"),
        ):
            pass  # Should not reach here

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "nonexistent-key"

    def test_signing_key_context_cleans_up_on_exception(self, vault_service):
        """Context manager should clean up resources even when exception occurs inside."""
        # Arrange: Write valid signing key
        import secrets

        secret_bytes = secrets.token_bytes(32)
        secret_hex = secret_bytes.hex()

        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": secret_hex},
        )

        # Act & Assert
        with (
            pytest.raises(RuntimeError),
            vault_service.signing_key_context("test-division", "key20260204") as (signing_key, _fragment),
        ):
            assert isinstance(signing_key, SigningKey)
            # Raise an exception inside the context
            raise RuntimeError("Test exception")

        # If we reach here, cleanup happened successfully (no exceptions during cleanup)


class TestDeleteSecret:
    """Tests for delete_secret method."""

    def test_delete_secret_removes_secret(self, vault_service):
        """Deleting a secret should remove it from vault."""
        # Arrange: Write a secret
        vault_service.write_secret("test/secret", {"key": "value"})

        # Verify it exists
        result = vault_service.fetch_secret("test/secret")
        assert result == {"key": "value"}

        # Act: Delete the secret
        vault_service.delete_secret("test/secret")

        # Assert: Verify it's gone
        from app.services.exceptions import SecretNotFoundError
        with pytest.raises(SecretNotFoundError):
            vault_service.fetch_secret("test/secret")

    def test_delete_secret_nonexistent_succeeds(self, vault_service):
        """Deleting a non-existent secret should not raise an error."""
        # Act & Assert: Should not raise
        vault_service.delete_secret("test/nonexistent")


class TestListSecrets:
    """Tests for list_secrets method."""

    def test_list_secrets_returns_keys(self, vault_service):
        """Listing secrets should return all keys at the path."""
        # Arrange: Write multiple secrets
        vault_service.write_secret("test/list/secret1", {"a": 1})
        vault_service.write_secret("test/list/secret2", {"b": 2})
        vault_service.write_secret("test/list/secret3", {"c": 3})

        # Act
        keys = vault_service.list_secrets("test/list")

        # Assert
        assert sorted(keys) == ["secret1", "secret2", "secret3"]

    def test_list_secrets_empty_path_returns_empty(self, vault_service):
        """Listing a non-existent path should return empty list."""
        # Act
        keys = vault_service.list_secrets("test/nonexistent/path")

        # Assert
        assert keys == []

    def test_list_secrets_exception_returns_empty(self, vault_service):
        """When client.list_secrets raises an exception, should return empty list."""
        # Arrange: Patch the client's list_secrets to raise an exception
        with patch.object(vault_service._client, 'list_secrets', side_effect=RuntimeError("Unexpected error")):
            # Act
            keys = vault_service.list_secrets("test/path")

            # Assert: Should return empty list instead of propagating exception
            assert keys == []
