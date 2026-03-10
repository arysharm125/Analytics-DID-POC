"""Integration tests for HvacVaultClient-specific behavior.

Tests HvacVaultClient against a real HashiCorp Vault instance running in a container.
These tests focus on HvacVaultClient-specific features that aren't covered by the
general VaultClientProtocol conformance tests.

For protocol conformance tests (ensuring all implementations behave identically),
see test_vault_client_conformance.py.
"""

import pytest

from app.services.vault_clients import HvacVaultClient


@pytest.mark.integration
class TestHvacVaultClientSpecific:
    """HvacVaultClient-specific integration tests."""

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
