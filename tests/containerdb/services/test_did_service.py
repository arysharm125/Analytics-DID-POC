"""Integration tests for app/services/did_service.py.

Tests DIDService initialization features that require real MongoDB
(collection validators, migrations, etc.).

These tests require a real MongoDB instance and won't work with mongomock.
Run with: pytest tests/containerdb/ --db-mode=container
"""

import pytest

from app.services.did_service import DIDService


class TestDIDServiceInitIntegration:
    """Integration tests for DIDService initialization with real MongoDB."""

    def test_init_runs_migrations(self, db_connector, vault_service, db_mode):
        """DIDService should run migrations and create collections with validators."""

        if db_mode != "container":
            pytest.skip("Test requires --db-mode=container")

        service = DIDService(
            db=db_connector,
            vault_svc=vault_service,
            run_migrations=True,
            ensure_signing_keys=False,
        )

        # Check that the artefacts collection exists
        collections = db_connector.db.list_collection_names()
        assert "did_artefacts" in collections

        # Verify collection has validators (this would fail with mongomock)
        collection_info = db_connector.db.command("listCollections", filter={"name": "did_artefacts"})
        collection_doc = collection_info["cursor"]["firstBatch"][0]
        assert "validator" in collection_doc["options"]

    def test_init_ensures_signing_keys_for_required_divisions(
        self, db_connector, vault_service, vault_mode, db_mode
    ):
        """DIDService should ensure signing keys exist for required divisions."""
        # This test requires clearing vault, only works with InMemoryVaultClient
        if vault_mode == "container":
            pytest.skip("Test requires InMemoryVaultClient (uses .clear() method)")
        if db_mode != "container":
            pytest.skip("Test requires --db-mode=container")

        # Clear vault to start fresh
        vault_service._client.clear()

        service = DIDService(
            db=db_connector,
            vault_svc=vault_service,
            run_migrations=True,
            ensure_signing_keys=True,
        )

        # Check that signing keys were created for required divisions
        for division in ["advisory", "epdw"]:
            fragments = vault_service.list_division_signing_key_fragments(division)
            assert len(fragments) > 0

    def test_init_without_ensuring_keys(self, db_connector, vault_service, vault_mode, db_mode):
        """DIDService with ensure_signing_keys=False should not create keys."""

        # This test requires clearing vault, only works with InMemoryVaultClient
        if vault_mode == "container":
            pytest.skip("Test requires InMemoryVaultClient (uses .clear() method)")
        if db_mode != "container":
            pytest.skip("Test requires --db-mode=container")

        # Clear vault to start fresh
        vault_service._client.clear()

        service = DIDService(
            db=db_connector,
            vault_svc=vault_service,
            run_migrations=True,
            ensure_signing_keys=False,
        )

        # Keys should not exist
        for division in ["advisory", "epdw"]:
            fragments = vault_service.list_division_signing_key_fragments(division)
            assert len(fragments) == 0
