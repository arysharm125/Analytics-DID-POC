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

        keys = vault_service.get_division_public_keys("test-division")

        assert len(keys) == 2
        assert keys[0]["fragment"] == "key20260204"
        assert keys[1]["fragment"] == "key20260205"
        assert "public_key_multibase" in keys[0]
        assert "public_key_multibase" in keys[1]

    def test_get_division_public_keys_empty_keys_raises(self, vault_service):
        """Getting public keys when keys list is empty should raise DivisionPublicKeysNotFoundError."""
        vault_service.write_secret(
            "divisions/test-division/public_keys",
            {"keys": []},
        )

        with pytest.raises(DivisionPublicKeysNotFoundError) as exc_info:
            vault_service.get_division_public_keys("test-division")

        assert exc_info.value.division == "test-division"
        assert "test-division" in str(exc_info.value)

    def test_get_division_public_keys_not_found_raises(self, vault_service):
        """Getting public keys when secret doesn't exist should raise DivisionPublicKeysNotFoundError."""
        with pytest.raises(DivisionPublicKeysNotFoundError) as exc_info:
            vault_service.get_division_public_keys("nonexistent-division")

        assert exc_info.value.division == "nonexistent-division"
        assert "nonexistent-division" in str(exc_info.value)

    def test_get_division_public_keys_missing_keys_field_raises(self, vault_service):
        """Getting public keys when secret exists but has no 'keys' field should raise DivisionPublicKeysNotFoundError."""
        vault_service.write_secret(
            "divisions/test-division/public_keys",
            {"other_field": "value"},
        )

        with pytest.raises(DivisionPublicKeysNotFoundError) as exc_info:
            vault_service.get_division_public_keys("test-division")

        assert exc_info.value.division == "test-division"


class TestGetSigningKeyHex:
    """Tests for get_signing_key_hex method."""

    def test_get_signing_key_hex_returns_hex_string(self, vault_service):
        """Getting signing key with valid data should return the hex string."""
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": "a" * 64},  # 32 bytes as hex
        )

        secret_hex = vault_service.get_signing_key_hex("test-division", "key20260204")

        assert secret_hex == "a" * 64
        assert len(secret_hex) == 64

    def test_get_signing_key_hex_not_found_raises(self, vault_service):
        """Getting signing key when secret doesn't exist should raise SigningKeyNotFoundError."""
        with pytest.raises(SigningKeyNotFoundError) as exc_info:
            vault_service.get_signing_key_hex("test-division", "nonexistent-key")

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "nonexistent-key"
        assert "test-division" in str(exc_info.value)
        assert "nonexistent-key" in str(exc_info.value)

    def test_get_signing_key_hex_missing_field_raises(self, vault_service):
        """Getting signing key when secret exists but has no 'secret_key_hex' field should raise SigningKeyNotFoundError."""
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"other_field": "value"},
        )

        with pytest.raises(SigningKeyNotFoundError) as exc_info:
            vault_service.get_signing_key_hex("test-division", "key20260204")

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"

    def test_get_signing_key_hex_empty_string_raises(self, vault_service):
        """Getting signing key when secret_key_hex is empty string should raise SigningKeyNotFoundError."""
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": ""},
        )

        with pytest.raises(SigningKeyNotFoundError) as exc_info:
            vault_service.get_signing_key_hex("test-division", "key20260204")

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"

    def test_get_signing_key_hex_none_raises(self, vault_service):
        """Getting signing key when secret_key_hex is None should raise SigningKeyNotFoundError."""
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": None},
        )

        with pytest.raises(SigningKeyNotFoundError) as exc_info:
            vault_service.get_signing_key_hex("test-division", "key20260204")

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"


class TestSigningKeyContext:
    """Tests for signing_key_context context manager."""

    def test_signing_key_context_yields_signing_key(self, vault_service):
        """Context manager should yield a valid SigningKey and fragment."""
        import secrets

        secret_bytes = secrets.token_bytes(32)
        secret_hex = secret_bytes.hex()

        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": secret_hex},
        )

        with vault_service.signing_key_context("test-division", "key20260204") as (signing_key, fragment):
            assert isinstance(signing_key, SigningKey)
            assert fragment == "key20260204"
            # Verify the signing key is usable
            test_message = b"test message"
            signature = signing_key.sign(test_message)
            assert signature is not None

    def test_signing_key_context_invalid_hex_raises(self, vault_service):
        """Context manager with invalid hex should raise SigningKeyNotFoundError."""
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": "not-valid-hex"},
        )

        with (
            pytest.raises(SigningKeyNotFoundError) as exc_info,
            vault_service.signing_key_context("test-division", "key20260204"),
        ):
            pass  # Should not reach here

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"

    def test_signing_key_context_invalid_length_raises(self, vault_service):
        """Context manager with wrong key length should raise SigningKeyNotFoundError."""
        import secrets

        wrong_length_bytes = secrets.token_bytes(16)
        wrong_hex = wrong_length_bytes.hex()

        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": wrong_hex},
        )

        with (
            pytest.raises(SigningKeyNotFoundError) as exc_info,
            vault_service.signing_key_context("test-division", "key20260204"),
        ):
            pass  # Should not reach here

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "key20260204"

    def test_signing_key_context_not_found_raises(self, vault_service):
        """Context manager when secret doesn't exist should raise SigningKeyNotFoundError."""
        with (
            pytest.raises(SigningKeyNotFoundError) as exc_info,
            vault_service.signing_key_context("test-division", "nonexistent-key"),
        ):
            pass  # Should not reach here

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "nonexistent-key"

    def test_signing_key_context_cleans_up_on_exception(self, vault_service):
        """Context manager should clean up resources even when exception occurs inside."""
        import secrets

        secret_bytes = secrets.token_bytes(32)
        secret_hex = secret_bytes.hex()

        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260204",
            {"secret_key_hex": secret_hex},
        )

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
        vault_service.write_secret("test/secret", {"key": "value"})

        result = vault_service.fetch_secret("test/secret")
        assert result == {"key": "value"}

        vault_service.delete_secret("test/secret")

        from app.services.exceptions import SecretNotFoundError
        with pytest.raises(SecretNotFoundError):
            vault_service.fetch_secret("test/secret")

    def test_delete_secret_nonexistent_succeeds(self, vault_service):
        """Deleting a non-existent secret should not raise an error."""
        vault_service.delete_secret("test/nonexistent")


class TestListSecrets:
    """Tests for list_secrets method."""

    def test_list_secrets_returns_keys(self, vault_service):
        """Listing secrets should return all keys at the path."""
        vault_service.write_secret("test/list/secret1", {"a": 1})
        vault_service.write_secret("test/list/secret2", {"b": 2})
        vault_service.write_secret("test/list/secret3", {"c": 3})

        keys = vault_service.list_secrets("test/list")

        assert sorted(keys) == ["secret1", "secret2", "secret3"]

    def test_list_secrets_empty_path_returns_empty(self, vault_service):
        """Listing a non-existent path should return empty list."""
        keys = vault_service.list_secrets("test/nonexistent/path")

        assert keys == []

    def test_list_secrets_exception_returns_empty(self, vault_service):
        """When client.list_secrets raises an exception, should return empty list."""
        with patch.object(vault_service._client, 'list_secrets', side_effect=RuntimeError("Unexpected error")):
            keys = vault_service.list_secrets("test/path")

            assert keys == []


class TestEnsureDivisionSigningKey:
    """Tests for ensure_division_signing_key method."""

    def test_ensure_signing_key_when_keys_exist_returns_latest(self, vault_service):
        """When signing keys already exist, should return latest fragment without creating new keys."""
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260101",
            {"secret_key_hex": "a" * 64},
        )
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260201",
            {"secret_key_hex": "b" * 64},
        )

        fragment = vault_service.ensure_division_signing_key("test-division")

        assert fragment == "key20260201"

        fragments = vault_service.list_division_signing_key_fragments("test-division")
        assert len(fragments) == 2

    def test_ensure_signing_key_creates_both_when_none_exist(self, vault_service):
        """When no keys exist, should create both signing key and public keys document."""
        fragment = vault_service.ensure_division_signing_key("test-division")

        assert fragment.startswith("key2026")

        secret_hex = vault_service.get_signing_key_hex("test-division", fragment)
        assert len(secret_hex) == 64  # 32 bytes as hex

        public_keys = vault_service.get_division_public_keys("test-division")
        assert len(public_keys) == 1
        assert public_keys[0]["fragment"] == fragment
        assert "public_key_multibase" in public_keys[0]
        assert public_keys[0]["public_key_multibase"].startswith("z")

    def test_ensure_signing_key_appends_to_existing_public_keys(self, vault_service):
        """When public keys exist but signing keys don't, should append to existing public keys list."""
        vault_service.write_secret(
            "divisions/test-division/public_keys",
            {
                "keys": [
                    {
                        "fragment": "key20260101",
                        "public_key_multibase": "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
                    }
                ]
            },
        )

        fragment = vault_service.ensure_division_signing_key("test-division")

        assert fragment.startswith("key2026")

        secret_hex = vault_service.get_signing_key_hex("test-division", fragment)
        assert len(secret_hex) == 64

        public_keys = vault_service.get_division_public_keys("test-division")
        assert len(public_keys) == 2
        assert public_keys[0]["fragment"] == "key20260101"
        assert public_keys[1]["fragment"] == fragment
        assert "public_key_multibase" in public_keys[1]

    def test_ensure_signing_key_is_idempotent(self, vault_service):
        """Calling ensure_division_signing_key multiple times should be idempotent."""
        fragment1 = vault_service.ensure_division_signing_key("test-division")
        fragment2 = vault_service.ensure_division_signing_key("test-division")
        fragment3 = vault_service.ensure_division_signing_key("test-division")

        assert fragment1 == fragment2 == fragment3

        fragments = vault_service.list_division_signing_key_fragments("test-division")
        assert len(fragments) == 1

        public_keys = vault_service.get_division_public_keys("test-division")
        assert len(public_keys) == 1


class TestGetActiveSigningKeyFragment:
    """Tests for get_active_signing_key_fragment method."""

    def test_get_active_fragment_returns_latest(self, vault_service):
        """When multiple signing keys exist, should return the latest fragment."""
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260101",
            {"secret_key_hex": "a" * 64},
        )
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260201",
            {"secret_key_hex": "b" * 64},
        )
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260115",
            {"secret_key_hex": "c" * 64},
        )

        fragment = vault_service.get_active_signing_key_fragment("test-division")

        assert fragment == "key20260201"

    def test_get_active_fragment_single_key(self, vault_service):
        """When only one signing key exists, should return that fragment."""
        vault_service.write_secret(
            "divisions/test-division/signing_keys/key20260101",
            {"secret_key_hex": "a" * 64},
        )

        fragment = vault_service.get_active_signing_key_fragment("test-division")

        assert fragment == "key20260101"

    def test_get_active_fragment_no_keys_raises(self, vault_service):
        """When no signing keys exist, should raise SigningKeyNotFoundError."""
        with pytest.raises(SigningKeyNotFoundError) as exc_info:
            vault_service.get_active_signing_key_fragment("test-division")

        assert exc_info.value.division == "test-division"
        assert exc_info.value.fragment == "<none>"
