"""Conformance tests for VaultClientProtocol implementations.

This module tests that all three vault client implementations (HvacVaultClient,
MockVaultClient, and InMemoryVaultClient) behave identically and conform to
the VaultClientProtocol interface.

These tests run as integration tests when --vault-mode=container is specified,
ensuring all three implementations are tested against the same test suite.
"""

from pathlib import Path

import pytest

from app.services.exceptions import SecretNotFoundError
from app.services.vault_clients import HvacVaultClient, InMemoryVaultClient
from app.services.vault_mock import MockVaultClient


@pytest.fixture(params=["in_memory", "file_mock", "hvac_real"])
def vault_client_impl(request, tmp_path, vault_container, vault_mode):
    """Parameterized fixture providing all three VaultClientProtocol implementations.

    This fixture creates instances of:
    - InMemoryVaultClient (fast in-memory mock)
    - MockVaultClient (file-based mock)
    - HvacVaultClient (real HashiCorp Vault)

    The HvacVaultClient tests are skipped when vault_mode != "container".
    """
    impl_type = request.param

    if impl_type == "in_memory":
        return InMemoryVaultClient()

    elif impl_type == "file_mock":
        mock_dir = tmp_path / "vault_mock"
        return MockVaultClient(root_dir=str(mock_dir), default_mount="secret")

    elif impl_type == "hvac_real":
        if vault_mode != "container":
            pytest.skip("HvacVaultClient tests require --vault-mode=container")

        if vault_container is None:
            pytest.skip("Vault container not available")

        host = vault_container.get_container_host_ip()
        port = vault_container.get_exposed_port(8200)
        addr = f"http://{host}:{port}"

        return HvacVaultClient(addr=addr, token="test-root-token")

    else:
        raise ValueError(f"Unknown implementation type: {impl_type}")


@pytest.mark.integration
class TestVaultClientConformance:
    """Conformance tests ensuring all VaultClientProtocol implementations behave identically."""

    def test_is_authenticated_returns_true(self, vault_client_impl):
        """All implementations should report as authenticated when properly configured."""
        assert vault_client_impl.is_authenticated() is True

    def test_write_and_read_secret(self, vault_client_impl):
        """Test basic write and read operations."""
        test_data = {"username": "admin", "password": "secret123"}

        vault_client_impl.write_secret("secret", "test/credentials", test_data)
        retrieved = vault_client_impl.read_secret("secret", "test/credentials")

        assert retrieved == test_data

    def test_read_nonexistent_secret_raises_secret_not_found_error(self, vault_client_impl):
        """All implementations should raise SecretNotFoundError for missing secrets."""
        with pytest.raises(SecretNotFoundError) as exc_info:
            vault_client_impl.read_secret("secret", "test/nonexistent")

        # Verify exception has correct attributes
        assert exc_info.value.mount_point == "secret"
        assert exc_info.value.path == "test/nonexistent"

    def test_write_overwrites_existing_secret(self, vault_client_impl):
        """Writing to the same path should overwrite the previous value."""
        # Write initial value
        vault_client_impl.write_secret("secret", "test/overwrite", {"version": 1})

        # Overwrite with new value
        new_data = {"version": 2, "updated": True}
        vault_client_impl.write_secret("secret", "test/overwrite", new_data)

        # Verify new value
        retrieved = vault_client_impl.read_secret("secret", "test/overwrite")
        assert retrieved == new_data

    def test_write_to_nested_path(self, vault_client_impl):
        """All implementations should support deeply nested paths."""
        test_data = {"value": "deeply nested"}
        path = "divisions/epdw/signing_keys/key1"

        vault_client_impl.write_secret("secret", path, test_data)
        retrieved = vault_client_impl.read_secret("secret", path)

        assert retrieved == test_data

    def test_write_complex_nested_data(self, vault_client_impl):
        """All implementations should handle complex nested data structures."""
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

        vault_client_impl.write_secret("secret", "test/complex", complex_data)
        retrieved = vault_client_impl.read_secret("secret", "test/complex")

        assert retrieved == complex_data

    def test_list_secrets_with_multiple_items(self, vault_client_impl):
        """Test listing secrets returns all items at a path."""
        # Create multiple secrets
        vault_client_impl.write_secret("secret", "test/list/secret1", {"a": 1})
        vault_client_impl.write_secret("secret", "test/list/secret2", {"b": 2})
        vault_client_impl.write_secret("secret", "test/list/secret3", {"c": 3})

        # List them
        result = vault_client_impl.list_secrets("secret", "test/list")

        assert sorted(result) == ["secret1", "secret2", "secret3"]

    def test_list_secrets_shows_directories_with_trailing_slash(self, vault_client_impl):
        """Nested paths should be shown with trailing '/' to indicate directories."""
        # Create secrets at different levels
        vault_client_impl.write_secret("secret", "test/nested/level1/secret1", {"a": 1})
        vault_client_impl.write_secret("secret", "test/nested/level2/secret2", {"b": 2})
        vault_client_impl.write_secret("secret", "test/nested/direct", {"c": 3})

        # List top level
        result = vault_client_impl.list_secrets("secret", "test/nested")

        # Should show direct secret and directories with trailing slash
        assert "direct" in result
        assert "level1/" in result
        assert "level2/" in result

    def test_list_secrets_empty_path_returns_empty_list(self, vault_client_impl):
        """Listing a nonexistent path should return an empty list."""
        result = vault_client_impl.list_secrets("secret", "test/nonexistent/path")
        assert result == []

    def test_delete_secret(self, vault_client_impl):
        """Test deleting a secret removes it completely."""
        # Create a secret
        vault_client_impl.write_secret("secret", "test/delete", {"data": "to be deleted"})

        # Verify it exists
        retrieved = vault_client_impl.read_secret("secret", "test/delete")
        assert retrieved == {"data": "to be deleted"}

        # Delete it
        vault_client_impl.delete_secret("secret", "test/delete")

        # Verify it's gone
        with pytest.raises(SecretNotFoundError):
            vault_client_impl.read_secret("secret", "test/delete")

    def test_delete_nonexistent_secret_succeeds(self, vault_client_impl):
        """Deleting a non-existent secret should not raise an error."""
        # Should not raise an exception
        vault_client_impl.delete_secret("secret", "test/nonexistent-delete")

    def test_multiple_writes_updates_value(self, vault_client_impl):
        """Multiple writes to the same path should update the value."""
        path = "test/versioned"

        # Write v1
        vault_client_impl.write_secret("secret", path, {"version": 1})
        assert vault_client_impl.read_secret("secret", path) == {"version": 1}

        # Write v2
        vault_client_impl.write_secret("secret", path, {"version": 2})
        assert vault_client_impl.read_secret("secret", path) == {"version": 2}

        # Write v3
        vault_client_impl.write_secret("secret", path, {"version": 3})
        assert vault_client_impl.read_secret("secret", path) == {"version": 3}

    def test_read_secret_returns_copy_not_reference(self, vault_client_impl):
        """Reading a secret should return a copy, not a reference to internal data."""
        original_data = {"key": "value"}
        vault_client_impl.write_secret("secret", "test/copy", original_data)

        # Read the secret
        retrieved1 = vault_client_impl.read_secret("secret", "test/copy")

        # Modify the retrieved data
        retrieved1["key"] = "modified"

        # Read again - should still have original value
        retrieved2 = vault_client_impl.read_secret("secret", "test/copy")
        assert retrieved2 == {"key": "value"}

    def test_concurrent_writes_to_different_paths(self, vault_client_impl):
        """Writing to different paths should not interfere with each other."""
        paths_data = {
            "test/concurrent/path1": {"id": 1},
            "test/concurrent/path2": {"id": 2},
            "test/concurrent/path3": {"id": 3},
        }

        # Write all secrets
        for path, data in paths_data.items():
            vault_client_impl.write_secret("secret", path, data)

        # Verify all were written correctly
        for path, expected_data in paths_data.items():
            retrieved = vault_client_impl.read_secret("secret", path)
            assert retrieved == expected_data
