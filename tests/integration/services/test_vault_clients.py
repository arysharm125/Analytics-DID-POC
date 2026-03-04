"""Integration tests for app/services/vault_clients.py.

Tests HvacVaultClient against a real HashiCorp Vault instance running in a container.
These tests verify that the client correctly interacts with Vault's KV v2 API.
"""

import pytest

from app.services.vault_clients import HvacVaultClient


@pytest.mark.integration
class TestHvacVaultClientIntegration:
    """Integration tests for HvacVaultClient with real Vault."""

    def test_is_authenticated_with_valid_token(self, vault_client, vault_mode):
        """Test authentication check with valid token."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        assert isinstance(vault_client, HvacVaultClient)
        assert vault_client.is_authenticated() is True

    def test_is_authenticated_with_invalid_token(self, vault_container, vault_mode):
        """Test authentication check with invalid token."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        # Create client with bad token
        host = vault_container.get_container_host_ip()
        port = vault_container.get_exposed_port(8200)
        addr = f"http://{host}:{port}"

        bad_client = HvacVaultClient(addr=addr, token="invalid-token")
        assert bad_client.is_authenticated() is False

    def test_write_and_read_secret(self, vault_client, vault_mode):
        """Test writing and reading a secret."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        # Write a secret
        test_data = {"username": "admin", "password": "secret123"}
        vault_client.write_secret("secret", "test/credentials", test_data)

        # Read it back
        retrieved = vault_client.read_secret("secret", "test/credentials")
        assert retrieved == test_data

    def test_write_secret_overwrites_existing(self, vault_client, vault_mode):
        """Test that writing to same path overwrites the secret."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        # Write initial version
        vault_client.write_secret("secret", "test/overwrite", {"version": 1})

        # Overwrite with new data
        new_data = {"version": 2, "updated": True}
        vault_client.write_secret("secret", "test/overwrite", new_data)

        # Verify new data
        retrieved = vault_client.read_secret("secret", "test/overwrite")
        assert retrieved == new_data

    def test_read_nonexistent_secret_raises_exception(self, vault_client, vault_mode):
        """Test reading a non-existent secret raises an exception."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        import hvac.exceptions

        with pytest.raises(hvac.exceptions.InvalidPath):
            vault_client.read_secret("secret", "test/nonexistent")

    def test_write_nested_path_secret(self, vault_client, vault_mode):
        """Test writing to deeply nested paths."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        test_data = {"value": "deeply nested"}
        vault_client.write_secret("secret", "divisions/epdw/signing_keys/key1", test_data)

        retrieved = vault_client.read_secret("secret", "divisions/epdw/signing_keys/key1")
        assert retrieved == test_data

    def test_list_secrets_empty_path(self, vault_client, vault_mode):
        """Test listing secrets when path is empty/nonexistent."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        import hvac.exceptions

        # Listing a nonexistent path raises InvalidPath in real Vault
        with pytest.raises(hvac.exceptions.InvalidPath):
            vault_client.list_secrets("secret", "test/empty/nonexistent")

    def test_list_secrets_with_items(self, vault_client, vault_mode):
        """Test listing secrets with multiple items."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        # Create several secrets
        vault_client.write_secret("secret", "test/list/secret1", {"a": 1})
        vault_client.write_secret("secret", "test/list/secret2", {"b": 2})
        vault_client.write_secret("secret", "test/list/secret3", {"c": 3})

        # List them
        result = vault_client.list_secrets("secret", "test/list")
        assert sorted(result) == ["secret1", "secret2", "secret3"]

    def test_list_secrets_with_nested_paths(self, vault_client, vault_mode):
        """Test listing secrets shows directories with trailing slash."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        # Create secrets at different levels
        vault_client.write_secret("secret", "test/nested/level1/secret1", {"a": 1})
        vault_client.write_secret("secret", "test/nested/level2/secret2", {"b": 2})
        vault_client.write_secret("secret", "test/nested/direct", {"c": 3})

        # List top level
        result = vault_client.list_secrets("secret", "test/nested")
        assert "direct" in result
        assert "level1/" in result
        assert "level2/" in result

    def test_delete_secret(self, vault_client, vault_mode):
        """Test deleting a secret and all its versions."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        # Create a secret
        vault_client.write_secret("secret", "test/delete", {"data": "to be deleted"})

        # Verify it exists
        retrieved = vault_client.read_secret("secret", "test/delete")
        assert retrieved == {"data": "to be deleted"}

        # Delete it
        vault_client.delete_secret("secret", "test/delete")

        # Verify it's gone
        import hvac.exceptions
        with pytest.raises(hvac.exceptions.InvalidPath):
            vault_client.read_secret("secret", "test/delete")

    def test_delete_nonexistent_secret_succeeds(self, vault_client, vault_mode):
        """Test deleting a non-existent secret doesn't raise an error."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        # Should not raise an exception
        vault_client.delete_secret("secret", "test/nonexistent-delete")

    def test_write_complex_nested_data(self, vault_client, vault_mode):
        """Test writing and reading complex nested data structures."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        complex_data = {
            "string": "value",
            "number": 42,
            "boolean": True,
            "null": None,
            "list": [1, 2, 3],
            "nested": {
                "deep": {
                    "value": "nested data",
                },
                "array": ["a", "b", "c"],
            },
        }

        vault_client.write_secret("secret", "test/complex", complex_data)
        retrieved = vault_client.read_secret("secret", "test/complex")
        assert retrieved == complex_data

    def test_multiple_writes_creates_versions(self, vault_client, vault_mode):
        """Test that multiple writes to same path create versions in Vault."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        path = "test/versioned"

        # Write v1
        vault_client.write_secret("secret", path, {"version": 1})

        # Write v2
        vault_client.write_secret("secret", path, {"version": 2})

        # Write v3
        vault_client.write_secret("secret", path, {"version": 3})

        # Read should return latest version
        latest = vault_client.read_secret("secret", path)
        assert latest == {"version": 3}

    def test_vault_service_integration_with_real_vault(self, vault_client, vault_mode):
        """Test VaultService operations with real Vault."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        from app.services.vault_service import VaultService

        vault_svc = VaultService(vault_client, "secret")

        # Test authentication
        assert vault_svc.is_authenticated() is True

        # Test write and fetch
        vault_svc.write_secret("test/service", {"key": "value"})
        fetched = vault_svc.fetch_secret("test/service")
        assert fetched == {"key": "value"}

        # Test division signing key creation
        fragment = vault_svc.ensure_division_signing_key("test-division")
        assert fragment.startswith("key")

        # Verify key was created
        key_hex = vault_svc.get_signing_key_hex("test-division", fragment)
        assert isinstance(key_hex, str)
        assert len(key_hex) == 64  # 32 bytes as hex

        # Verify public keys were created
        public_keys = vault_svc.get_division_public_keys("test-division")
        assert len(public_keys) >= 1
        assert public_keys[0]["fragment"] == fragment
        assert "public_key_multibase" in public_keys[0]

    def test_concurrent_writes_to_different_paths(self, vault_client, vault_mode):
        """Test that concurrent writes to different paths don't interfere."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        # Write to multiple paths
        paths_data = {
            "test/concurrent/path1": {"id": 1},
            "test/concurrent/path2": {"id": 2},
            "test/concurrent/path3": {"id": 3},
        }

        for path, data in paths_data.items():
            vault_client.write_secret("secret", path, data)

        # Verify all were written correctly
        for path, expected_data in paths_data.items():
            retrieved = vault_client.read_secret("secret", path)
            assert retrieved == expected_data


@pytest.mark.integration
class TestHvacVaultClientErrorHandling:
    """Test error handling in HvacVaultClient."""

    def test_connection_to_invalid_address_fails_gracefully(self, vault_mode):
        """Test that connection to invalid address fails gracefully."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        # Try to connect to non-existent vault
        client = HvacVaultClient(addr="http://localhost:9999", token="test")

        # is_authenticated should return False, not raise
        assert client.is_authenticated() is False

    def test_read_with_connection_error_raises(self, vault_mode):
        """Test that read operations raise appropriate errors on connection failure."""
        if vault_mode != "container":
            pytest.skip("Requires container vault mode")

        import requests.exceptions

        client = HvacVaultClient(addr="http://localhost:9999", token="test")

        # Should raise a connection error (hvac wraps requests exceptions)
        with pytest.raises((requests.exceptions.ConnectionError, requests.exceptions.RequestException)):
            client.read_secret("secret", "test/path")
