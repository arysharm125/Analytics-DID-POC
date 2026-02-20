"""Unit tests for app/services/did_service.py.

Tests the DIDService class methods, helper functions, and business logic.
Uses mongomock and InMemoryVaultClient for isolated unit testing.
"""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch, MagicMock
import uuid

import pytest
from pydantic import ValidationError

from app.services.did_service import (
    DIDService,
    ArtefactInput,
    ArtefactRecord,
    ProvenanceNode,
    _artefact_has_changes,
    _artefact_to_da_vc_input,
)
from app.services.exceptions import (
    ArtefactNoChangesError,
    ArtefactNotFoundError,
    DivisionKeysNotFound,
    DivisionMismatchError,
    ProvenanceNotFoundError,
    VersionConflictError,
)
from app.did_utils.jsonld import DigitalArtefactVCInput


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def did_service_no_migrations(db_connector, vault_service):
    """Create a DIDService without running migrations (for mongomock compatibility).

    Mongomock doesn't support validator parameters in create_collection,
    so we manually create the collection and indexes instead.
    """
    # Manually create the did_artefacts collection with indexes
    collection = db_connector.get_collection("did_artefacts")

    # Create indexes (mongomock supports these)
    collection.create_index([("version_uid", 1)], unique=True, name="idx_version_uid")
    collection.create_index(
        [("external_uid", 1), ("version", 1)],
        unique=True,
        name="idx_external_uid_version"
    )
    collection.create_index([("provenance", 1)], name="idx_provenance")

    # Create DIDService without running migrations
    return DIDService(
        db=db_connector,
        vault_svc=vault_service,
        run_migrations=False,
        ensure_signing_keys=False,
    )


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestArtefactHasChanges:
    """Tests for _artefact_has_changes helper function."""

    def test_no_changes_returns_false(self):
        """No changes in any field should return False."""
        existing = {
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            "artefact_metadata": {"key": "value"},
            "provenance": ["uuid-1", "uuid-2"],
        }
        result = _artefact_has_changes(
            existing=existing,
            new_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            new_metadata={"key": "value"},
            new_provenance=["uuid-1", "uuid-2"],
        )
        assert result is False

    def test_hash_change_returns_true(self):
        """Change in artefact_hash should return True."""
        existing = {
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            "artefact_metadata": {"key": "value"},
            "provenance": None,
        }
        result = _artefact_has_changes(
            existing=existing,
            new_hash="QmNewHash",
            new_metadata={"key": "value"},
            new_provenance=None,
        )
        assert result is True

    def test_metadata_change_returns_true(self):
        """Change in artefact_metadata should return True."""
        existing = {
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            "artefact_metadata": {"key": "value"},
            "provenance": None,
        }
        result = _artefact_has_changes(
            existing=existing,
            new_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            new_metadata={"key": "new_value"},
            new_provenance=None,
        )
        assert result is True

    def test_metadata_deep_change_returns_true(self):
        """Deep change in nested metadata should return True."""
        existing = {
            "artefact_hash": None,
            "artefact_metadata": {"outer": {"inner": "value"}},
            "provenance": None,
        }
        result = _artefact_has_changes(
            existing=existing,
            new_hash=None,
            new_metadata={"outer": {"inner": "new_value"}},
            new_provenance=None,
        )
        assert result is True

    def test_provenance_change_returns_true(self):
        """Change in provenance list should return True."""
        existing = {
            "artefact_hash": None,
            "artefact_metadata": None,
            "provenance": ["uuid-1", "uuid-2"],
        }
        result = _artefact_has_changes(
            existing=existing,
            new_hash=None,
            new_metadata=None,
            new_provenance=["uuid-1", "uuid-3"],
        )
        assert result is True

    def test_provenance_none_vs_empty_list_no_change(self):
        """None and empty list in provenance should be treated as equal."""
        existing = {
            "artefact_hash": None,
            "artefact_metadata": None,
            "provenance": None,
        }
        result = _artefact_has_changes(
            existing=existing,
            new_hash=None,
            new_metadata=None,
            new_provenance=[],
        )
        assert result is False

    def test_multiple_changes_returns_true(self):
        """Multiple changes should return True."""
        existing = {
            "artefact_hash": "QmOld",
            "artefact_metadata": {"key": "old"},
            "provenance": ["uuid-1"],
        }
        result = _artefact_has_changes(
            existing=existing,
            new_hash="QmNew",
            new_metadata={"key": "new"},
            new_provenance=["uuid-2"],
        )
        assert result is True


class TestArtefactToDaVcInput:
    """Tests for _artefact_to_da_vc_input helper function."""

    def test_minimal_artefact_converts_correctly(self):
        """Minimal artefact with required fields only."""
        artefact = {
            "external_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "version": 1,
            "version_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9d",
            "created_at": datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc),
            "division": "epdw",
        }
        result = _artefact_to_da_vc_input(artefact)
        assert isinstance(result, DigitalArtefactVCInput)
        assert result.uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert result.version == 1
        assert result.version_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9d"
        assert result.hash is None
        assert result.metadata is None
        assert result.provenance is None

    def test_full_artefact_with_all_fields(self):
        """Artefact with all optional fields populated."""
        artefact = {
            "external_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "version": 2,
            "version_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9d",
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            "artefact_metadata": {"key": "value"},
            "created_at": datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc),
            "division": "advisory",
            "provenance": ["uuid-1", "uuid-2"],
        }
        result = _artefact_to_da_vc_input(artefact)
        assert result.hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"
        assert result.metadata == {"key": "value"}
        assert result.provenance == ["uuid-1", "uuid-2"]
        assert result.division == "advisory"

    def test_optional_fields_handled(self):
        """Missing optional fields should be None."""
        artefact = {
            "external_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "version": 1,
            "version_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9d",
            "created_at": datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc),
            "division": "epdw",
        }
        result = _artefact_to_da_vc_input(artefact)
        assert result.hash is None
        assert result.metadata is None
        assert result.provenance is None


# =============================================================================
# DIDService Initialization Tests
# =============================================================================


class TestDIDServiceInit:
    """Tests for DIDService initialization."""

    def test_init_without_migrations(self, db_connector, vault_service):
        """DIDService with run_migrations=False should not create collections."""
        service = DIDService(
            db=db_connector,
            vault_svc=vault_service,
            run_migrations=False,
            ensure_signing_keys=False,
        )
        collections = db_connector.db.list_collection_names()
        assert "did_artefacts" not in collections


# =============================================================================
# Artefact CRUD Tests
# =============================================================================


class TestUpsertArtefact:
    """Tests for upsert_artefact method."""

    def test_create_first_version(self, did_service_no_migrations):
        """Creating first version should set version=1."""
        did_service = did_service_no_migrations
        artefact_input = ArtefactInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            division="epdw",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
        )
        result = did_service.upsert_artefact(artefact_input)

        assert isinstance(result, ArtefactRecord)
        assert result.external_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert result.version == 1
        assert result.division == "epdw"
        assert result.revoked is False
        assert result.version_uid is not None

    def test_create_with_all_optional_fields(self, did_service_no_migrations):
        """Creating artefact with all optional fields."""
        did_service = did_service_no_migrations
        artefact_input = ArtefactInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            division="advisory",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            artefact_metadata={"key": "value", "nested": {"data": 123}},
            created_at=datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc),
        )
        result = did_service.upsert_artefact(artefact_input)

        assert result.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"
        assert result.artefact_metadata == {"key": "value", "nested": {"data": 123}}
        assert result.created_at == datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc)

    def test_create_with_provenance(self, did_service_no_migrations):
        """Creating artefact with provenance references."""
        did_service = did_service_no_migrations
        # First create parent artefacts
        parent1 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000005",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Par111",
            )
        )
        parent2 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000006",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Par222",
            )
        )

        # Create child with provenance
        child_input = ArtefactInput(
            external_uid="95da4dd5-6e48-0000-bb91-000000000002",
            division="epdw",
            artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d8",
            provenance=[parent1.version_uid, parent2.external_uid],
        )
        result = did_service.upsert_artefact(child_input)

        assert result.provenance is not None
        assert len(result.provenance) == 2
        # Provenance should be canonicalized to UUIDs
        assert parent1.version_uid in result.provenance
        assert parent2.external_uid in result.provenance

    def test_update_creates_new_version(self, did_service_no_migrations):
        """Updating an artefact should create a new version."""
        did_service = did_service_no_migrations
        # Create first version
        v1 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            )
        )

        # Update with new hash
        v2 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
            )
        )

        assert v2.version == 2
        assert v2.version_uid != v1.version_uid
        assert v2.external_uid == v1.external_uid

    def test_update_increments_version_number(self, did_service_no_migrations):
        """Multiple updates should increment version correctly."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        v1 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1")
        )
        v2 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2")
        )
        v3 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA3t8auVZRn8x5M3kN1p6yZR2oG7wJGD3")
        )

        assert v1.version == 1
        assert v2.version == 2
        assert v3.version == 3

    def test_update_with_metadata_change(self, did_service_no_migrations):
        """Updating only metadata should create new version."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        v1 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid=external_uid,
                division="epdw",
                artefact_metadata={"version": 1},
            )
        )
        v2 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid=external_uid,
                division="epdw",
                artefact_metadata={"version": 2},
            )
        )

        assert v2.version == 2
        assert v2.artefact_metadata == {"version": 2}

    def test_update_with_provenance_change(self, did_service_no_migrations):
        """Updating only provenance should create new version."""
        did_service = did_service_no_migrations
        parent = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-000000000001", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent")
        )
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        v1 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", provenance=[])
        )
        v2 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid=external_uid, division="epdw", provenance=[parent.version_uid]
            )
        )

        assert v2.version == 2
        assert v2.provenance == [parent.version_uid]

    def test_created_at_uses_provided_timestamp(self, did_service_no_migrations):
        """When created_at is provided, it should be used."""
        did_service = did_service_no_migrations
        custom_time = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                created_at=custom_time,
            )
        )
        assert result.created_at == custom_time

    def test_created_at_defaults_to_now(self, did_service_no_migrations):
        """When created_at is not provided, it should default to now."""
        did_service = did_service_no_migrations
        before = datetime.now(timezone.utc)
        result = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
            )
        )
        after = datetime.now(timezone.utc)
        assert before <= result.created_at <= after

    def test_division_mismatch_raises(self, did_service_no_migrations):
        """Attempting to change division should raise DivisionMismatchError."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1")
        )

        with pytest.raises(DivisionMismatchError) as exc:
            did_service.upsert_artefact(
                ArtefactInput(
                    external_uid=external_uid, division="advisory", artefact_hash="QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2"
                )
            )
        assert "epdw" in str(exc.value)
        assert "advisory" in str(exc.value)

    def test_no_changes_raises(self, did_service_no_migrations):
        """Upserting with no changes should raise ArtefactNoChangesError."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        did_service.upsert_artefact(
            ArtefactInput(
                external_uid=external_uid,
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                artefact_metadata={"key": "value"},
            )
        )

        with pytest.raises(ArtefactNoChangesError) as exc:
            did_service.upsert_artefact(
                ArtefactInput(
                    external_uid=external_uid,
                    division="epdw",
                    artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                    artefact_metadata={"key": "value"},
                )
            )
        assert external_uid in str(exc.value)

    def test_invalid_provenance_raises(self, did_service_no_migrations):
        """Provenance referencing non-existent artefact should raise."""
        did_service = did_service_no_migrations
        with pytest.raises(ProvenanceNotFoundError) as exc:
            did_service.upsert_artefact(
                ArtefactInput(
                    external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                    division="epdw",
                    provenance=["95da4dd5-9999-9999-9999-999999999999"],
                )
            )
        assert "95da4dd5-9999-9999-9999-999999999999" in str(exc.value)


class TestFindByExternalUid:
    """Tests for find_by_external_uid method."""

    def test_find_existing_artefact(self, did_service_no_migrations):
        """Finding an existing artefact should return it."""
        did_service = did_service_no_migrations
        created = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            )
        )

        result = did_service.find_by_external_uid("95da4dd5-6e48-4c5b-bb91-935983c16d9c")
        assert result is not None
        assert result.external_uid == created.external_uid
        assert result.version == created.version

    def test_find_returns_latest_version(self, did_service_no_migrations):
        """Finding should return the latest version."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        v1 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1")
        )
        v2 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2")
        )
        v3 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA3t8auVZRn8x5M3kN1p6yZR2oG7wJGD3")
        )

        result = did_service.find_by_external_uid(external_uid)
        assert result.version == 3
        assert result.version_uid == v3.version_uid

    def test_find_with_division_filter(self, did_service_no_migrations):
        """Finding with division filter should return only matching division."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1")
        )

        result = did_service.find_by_external_uid(external_uid, division="epdw")
        assert result is not None
        assert result.division == "epdw"

    def test_find_with_wrong_division_returns_none(self, did_service_no_migrations):
        """Finding with wrong division filter should return None."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1")
        )

        result = did_service.find_by_external_uid(external_uid, division="advisory")
        assert result is None

    def test_find_nonexistent_returns_none(self, did_service_no_migrations):
        """Finding non-existent artefact should return None."""
        did_service = did_service_no_migrations
        result = did_service.find_by_external_uid("nonexistent-uuid")
        assert result is None


class TestFindByProvenance:
    """Tests for find_by_provenance method."""

    def test_find_by_provenance_returns_matching(self, did_service_no_migrations):
        """Finding by provenance should return artefacts with that provenance."""
        did_service = did_service_no_migrations
        parent = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-000000000001", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent")
        )

        child1 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000003",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7C1Hi1d",
                provenance=[parent.version_uid],
            )
        )
        child2 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000004",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d2",
                provenance=[parent.version_uid],
            )
        )

        results = did_service.find_by_provenance(parent.version_uid)
        assert len(results) == 2
        uids = {r.external_uid for r in results}
        assert "95da4dd5-6e48-0000-bb91-000000000003" in uids
        assert "95da4dd5-6e48-0000-bb91-000000000004" in uids

    def test_find_by_provenance_returns_only_latest_versions(self, did_service_no_migrations):
        """Finding by provenance should return only latest version of each artefact."""
        did_service = did_service_no_migrations
        parent = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-000000000001", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent")
        )

        # Create child with multiple versions
        child_v1 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000002",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7C1Hi1d",
                provenance=[parent.version_uid],
            )
        )
        child_v2 = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000002",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d2",
                provenance=[parent.version_uid],
            )
        )

        results = did_service.find_by_provenance(parent.version_uid)
        assert len(results) == 1
        assert results[0].version == 2
        assert results[0].version_uid == child_v2.version_uid

    def test_find_by_provenance_with_division_filter(self, did_service_no_migrations):
        """Finding by provenance with division filter."""
        did_service = did_service_no_migrations
        parent = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-000000000001", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent")
        )

        epdw_child = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-00000000000f",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Epdw11",
                provenance=[parent.version_uid],
            )
        )
        advisory_child = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000010",
                division="advisory",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Advis1",
                provenance=[parent.version_uid],
            )
        )

        results = did_service.find_by_provenance(parent.version_uid, division="epdw")
        assert len(results) == 1
        assert results[0].division == "epdw"

    def test_find_by_provenance_no_matches_returns_empty(self, did_service_no_migrations):
        """Finding by provenance with no matches should return empty list."""
        did_service = did_service_no_migrations
        results = did_service.find_by_provenance("nonexistent-uuid")
        assert results == []


class TestGetDescendants:
    """Tests for get_descendants method."""

    def test_get_descendants_by_version_uid(self, did_service_no_migrations):
        """Get descendants using version_uid should work."""
        did_service = did_service_no_migrations
        parent = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-000000000001", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent")
        )
        child = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000002",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1",
                provenance=[parent.version_uid],
            )
        )

        descendants = did_service.get_descendants(parent.version_uid)
        assert len(descendants) == 1
        assert descendants[0]["external_uid"] == "95da4dd5-6e48-0000-bb91-000000000002"

    def test_get_descendants_by_external_uid(self, did_service_no_migrations):
        """Get descendants using external_uid should work."""
        did_service = did_service_no_migrations
        parent = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-000000000001", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent")
        )
        child = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000002",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1",
                provenance=[parent.external_uid],
            )
        )

        descendants = did_service.get_descendants(parent.external_uid)
        assert len(descendants) == 1
        assert descendants[0]["external_uid"] == "95da4dd5-6e48-0000-bb91-000000000002"

    def test_get_descendants_no_matches_returns_empty(self, did_service_no_migrations):
        """Get descendants with no children should return empty list."""
        did_service = did_service_no_migrations
        parent = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-000000000001", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent")
        )

        descendants = did_service.get_descendants(parent.version_uid)
        assert descendants == []

    def test_get_descendants_nonexistent_uid_returns_empty(self, did_service_no_migrations):
        """Get descendants for non-existent uid should return empty list."""
        did_service = did_service_no_migrations
        descendants = did_service.get_descendants("nonexistent-uuid")
        assert descendants == []


# =============================================================================
# Artefact Overview & Provenance Tree Tests
# =============================================================================


class TestGetArtefactOverview:
    """Tests for get_artefact_overview method."""

    def test_overview_returns_artefact(self, did_service_no_migrations):
        """Overview should return the artefact document."""
        did_service = did_service_no_migrations
        created = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            )
        )

        artefact, latest = did_service.get_artefact_overview(created.version_uid)
        assert artefact["version_uid"] == created.version_uid
        assert artefact["version"] == 1

    def test_overview_with_newer_version(self, did_service_no_migrations):
        """Overview should return latest version when newer exists."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        v1 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1")
        )
        v2 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2")
        )

        artefact, latest = did_service.get_artefact_overview(v1.version_uid)
        assert artefact["version"] == 1
        assert latest is not None
        assert latest["version"] == 2
        assert latest["version_uid"] == v2.version_uid

    def test_overview_no_newer_version(self, did_service_no_migrations):
        """Overview should return None for latest when no newer version."""
        did_service = did_service_no_migrations
        created = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            )
        )

        artefact, latest = did_service.get_artefact_overview(created.version_uid)
        assert artefact["version"] == 1
        assert latest is None

    def test_overview_by_version_uid(self, did_service_no_migrations):
        """Overview using version_uid should return that specific version."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        v1 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1")
        )
        v2 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2")
        )

        artefact, latest = did_service.get_artefact_overview(v1.version_uid)
        assert artefact["version"] == 1

    def test_overview_by_external_uid(self, did_service_no_migrations):
        """Overview using external_uid should return latest version."""
        did_service = did_service_no_migrations
        external_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        v1 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1")
        )
        v2 = did_service.upsert_artefact(
            ArtefactInput(external_uid=external_uid, division="epdw", artefact_hash="QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2")
        )

        artefact, latest = did_service.get_artefact_overview(external_uid)
        assert artefact["version"] == 2

    def test_overview_not_found_raises(self, did_service_no_migrations):
        """Overview for non-existent uid should raise ArtefactNotFoundError."""
        did_service = did_service_no_migrations
        with pytest.raises(ArtefactNotFoundError):
            did_service.get_artefact_overview("nonexistent-uuid")


class TestGetProvenanceTree:
    """Tests for get_provenance_tree method."""

    def test_tree_single_level(self, did_service_no_migrations):
        """Provenance tree with single level."""
        did_service = did_service_no_migrations
        parent = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-000000000001", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent")
        )
        child = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000002",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1",
                provenance=[parent.version_uid],
            )
        )

        tree = did_service.get_provenance_tree(child.version_uid)
        assert len(tree) == 1
        assert tree[0].uid == parent.version_uid
        assert tree[0].division == "epdw"
        assert tree[0].children is None

    def test_tree_multiple_levels(self, did_service_no_migrations):
        """Provenance tree with multiple levels."""
        did_service = did_service_no_migrations
        grandparent = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-000000000007", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Grandp")
        )
        parent = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000008",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent",
                provenance=[grandparent.version_uid],
            )
        )
        child = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-000000000009",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1",
                provenance=[parent.version_uid],
            )
        )

        tree = did_service.get_provenance_tree(child.version_uid)
        assert len(tree) == 1
        assert tree[0].uid == parent.version_uid
        assert tree[0].children is not None
        assert len(tree[0].children) == 1
        assert tree[0].children[0].uid == grandparent.version_uid

    def test_tree_respects_max_depth(self, did_service_no_migrations):
        """Provenance tree should respect max_depth parameter."""
        did_service = did_service_no_migrations
        gp = did_service.upsert_artefact(
            ArtefactInput(external_uid="95da4dd5-6e48-0000-bb91-00000000000a", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Grandp")
        )
        p = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-00000000000b", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent", provenance=[gp.version_uid]
            )
        )
        c = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-00000000000c", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1", provenance=[p.version_uid]
            )
        )

        tree = did_service.get_provenance_tree(c.version_uid, max_depth=1)
        assert len(tree) == 1
        assert tree[0].uid == p.version_uid
        # Should be truncated since p has provenance but max_depth=1
        assert tree[0].truncated is True
        assert tree[0].children is None

    def test_tree_respects_max_children(self, did_service_no_migrations):
        """Provenance tree should respect max_children parameter."""
        did_service = did_service_no_migrations
        # Create many parents
        parents = []
        for i in range(15):
            parent = did_service.upsert_artefact(
                ArtefactInput(
                    external_uid=f"95da4dd5-6e48-{i:04d}-bb91-000000000100", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZRXG7Parent"
                )
            )
            parents.append(parent.version_uid)

        # Create child with many parents
        child = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-00000000000e",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1",
                provenance=parents,
            )
        )

        tree = did_service.get_provenance_tree(child.version_uid, max_children=10)
        # Should return all parents but mark as truncated (not recursed)
        assert len(tree) == 15
        # All should be marked as not truncated (they have no children)
        for node in tree:
            assert node.truncated is False

    def test_tree_marks_truncated_nodes(self, did_service_no_migrations):
        """Nodes exceeding max_children should be marked truncated."""
        did_service = did_service_no_migrations
        # Create grandparents
        grandparents = []
        for i in range(15):
            gp = did_service.upsert_artefact(
                ArtefactInput(
                    external_uid=f"95da4dd5-6e48-{i:04d}-bb91-000000000200", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1pyXR2G7GrandpX"
                )
            )
            grandparents.append(gp.version_uid)

        # Create parent with many grandparents
        parent = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-00000000000d",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent",
                provenance=grandparents,
            )
        )

        # Create child
        child = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-00000000000e",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1",
                provenance=[parent.version_uid],
            )
        )

        tree = did_service.get_provenance_tree(child.version_uid, max_children=10)
        assert len(tree) == 1
        assert tree[0].uid == parent.version_uid
        # Parent has 15 provenance items > max_children=10, so it should be truncated
        assert tree[0].truncated is True
        assert tree[0].children is None

    def test_tree_handles_not_found_provenance(self, did_service_no_migrations):
        """Provenance tree should handle references to non-existent artefacts."""
        did_service = did_service_no_migrations
        child = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-00000000000e",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1",
                # Cannot actually insert with invalid provenance due to validation,
                # so we'll manually insert a document with invalid provenance
            )
        )

        # Manually add invalid provenance to the document
        collection = did_service.db.get_collection(did_service._artefacts_col_name)
        collection.update_one(
            {"version_uid": child.version_uid},
            {"$set": {"provenance": ["nonexistent-uuid"]}},
        )

        tree = did_service.get_provenance_tree(child.version_uid)
        assert len(tree) == 1
        assert tree[0].uid == "nonexistent-uuid"
        assert tree[0].division is None  # Not found
        assert tree[0].truncated is False
        assert tree[0].children is None

    def test_tree_root_not_found_raises(self, did_service_no_migrations):
        """Provenance tree for non-existent root should raise."""
        did_service = did_service_no_migrations
        with pytest.raises(ArtefactNotFoundError):
            did_service.get_provenance_tree("nonexistent-uuid")

    def test_tree_empty_provenance_returns_empty(self, did_service_no_migrations):
        """Provenance tree with no provenance should return empty list."""
        did_service = did_service_no_migrations
        artefact = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-0000-bb91-00000000000e", division="epdw", artefact_hash="QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1", provenance=[]
            )
        )

        tree = did_service.get_provenance_tree(artefact.version_uid)
        assert tree == []


# =============================================================================
# Division Key Management Tests
# =============================================================================


class TestFetchDivisionPubKeys:
    """Tests for _fetch_division_pub_keys method."""

    def test_fetch_existing_keys(self, did_service_no_migrations, vault_service):
        """Fetching existing public keys should return them."""
        did_service = did_service_no_migrations
        # Ensure keys exist
        vault_service.ensure_division_signing_key("epdw")

        keys = did_service._fetch_division_pub_keys("epdw")
        assert isinstance(keys, list)
        assert len(keys) > 0
        assert "fragment" in keys[0]
        assert "public_key_multibase" in keys[0]

    def test_fetch_missing_keys_raises(self, did_service_no_migrations, vault_service):
        """Fetching missing keys should raise DivisionKeysNotFound."""
        did_service = did_service_no_migrations
        # Clear vault
        vault_service._client.clear()

        with pytest.raises(DivisionKeysNotFound) as exc:
            did_service._fetch_division_pub_keys("nonexistent")
        assert "nonexistent" in str(exc.value)


class TestGetActiveSigningKeyFragment:
    """Tests for _get_active_signing_key_fragment method."""

    def test_get_active_fragment(self, did_service_no_migrations, vault_service):
        """Get active fragment should return the latest key."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")
        fragment = did_service._get_active_signing_key_fragment("epdw")
        assert isinstance(fragment, str)
        assert fragment.startswith("key")

    def test_get_active_fragment_multiple_keys(self, did_service_no_migrations, vault_service):
        """With multiple keys, should return the latest (sorted)."""
        did_service = did_service_no_migrations
        # Manually add multiple keys
        vault_service.write_secret(
            "divisions/epdw/signing_keys/key20260101", {"secret_key_hex": "a" * 64}
        )
        vault_service.write_secret(
            "divisions/epdw/signing_keys/key20260201", {"secret_key_hex": "b" * 64}
        )

        fragment = did_service._get_active_signing_key_fragment("epdw")
        assert fragment == "key20260201"

    def test_get_active_fragment_no_keys_raises(self, did_service_no_migrations, vault_service):
        """Get active fragment with no keys should raise."""
        did_service = did_service_no_migrations
        vault_service._client.clear()

        with pytest.raises(DivisionKeysNotFound):
            did_service._get_active_signing_key_fragment("nonexistent")


# =============================================================================
# DID Document Generation Tests
# =============================================================================


class TestDivisionDidDoc:
    """Tests for division_did_doc method."""

    def test_generates_valid_did_doc_structure(self, did_service_no_migrations, vault_service):
        """Generated DID document should have valid structure."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        did_doc = did_service.division_did_doc("epdw")

        assert "@context" in did_doc
        assert "id" in did_doc
        assert "verificationMethod" in did_doc
        assert "assertionMethod" in did_doc
        assert did_doc["id"] == "did:web:did.amd.com:epdw"

    def test_includes_all_verification_methods(self, did_service_no_migrations, vault_service):
        """DID document should include all verification methods."""
        did_service = did_service_no_migrations
        # Add multiple keys
        vault_service.ensure_division_signing_key("epdw")
        vault_service.write_secret(
            "divisions/epdw/public_keys",
            {
                "keys": [
                    {
                        "fragment": "key1",
                        "public_key_multibase": "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK",
                    },
                    {
                        "fragment": "key2",
                        "public_key_multibase": "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doL",
                    },
                ]
            },
        )

        did_doc = did_service.division_did_doc("epdw")
        assert len(did_doc["verificationMethod"]) == 2

    def test_includes_assertion_method_refs(self, did_service_no_migrations, vault_service):
        """DID document should include assertionMethod references."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        did_doc = did_service.division_did_doc("epdw")
        assert isinstance(did_doc["assertionMethod"], list)
        assert len(did_doc["assertionMethod"]) > 0
        # References should be full URIs
        assert all(ref.startswith("did:web:did.amd.com:epdw#") for ref in did_doc["assertionMethod"])

    def test_missing_keys_raises(self, did_service_no_migrations, vault_service):
        """Division with no keys should raise DivisionKeysNotFound."""
        did_service = did_service_no_migrations
        vault_service._client.clear()

        with pytest.raises(DivisionKeysNotFound):
            did_service.division_did_doc("nonexistent")


# =============================================================================
# Verifiable Credential Generation Tests
# =============================================================================


class TestArtefactVc:
    """Tests for artefact_vc method."""

    def test_generates_signed_vc(self, did_service_no_migrations, vault_service):
        """artefact_vc should generate a signed VC."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        artefact = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            )
        )

        vc = did_service.artefact_vc("epdw", artefact.version_uid)

        assert "@context" in vc
        assert "type" in vc
        assert "credentialSubject" in vc
        assert "proof" in vc
        assert vc["type"] == ["VerifiableCredential", "DigitalArtefactCredential"]

    def test_vc_includes_correct_artefact_data(self, did_service_no_migrations, vault_service):
        """VC should include correct artefact data."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        artefact = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
                artefact_metadata={"key": "value"},
            )
        )

        vc = did_service.artefact_vc("epdw", artefact.version_uid)

        subject = vc["credentialSubject"]
        assert "did:web:did.amd.com:" + artefact.external_uid in subject["id"]
        assert subject["version"] == artefact.version
        assert subject["artefactHash"] == artefact.artefact_hash

    def test_vc_with_specific_division(self, did_service_no_migrations, vault_service):
        """VC with specific division should use that division."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        artefact = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            )
        )

        vc = did_service.artefact_vc("epdw", artefact.version_uid)
        assert "did:web:did.amd.com:epdw" in vc["proof"]["verificationMethod"]

    def test_vc_without_division_uses_artefact_division(self, did_service_no_migrations, vault_service):
        """VC without division parameter should use artefact's division."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("advisory")

        artefact = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="advisory",
                artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            )
        )

        vc = did_service.artefact_vc(None, artefact.version_uid)
        assert "did:web:did.amd.com:advisory" in vc["proof"]["verificationMethod"]

    def test_artefact_not_found_raises(self, did_service_no_migrations):
        """VC for non-existent artefact should raise ArtefactNotFoundError."""
        did_service = did_service_no_migrations
        with pytest.raises(ArtefactNotFoundError):
            did_service.artefact_vc("epdw", "nonexistent-uuid")

    def test_division_mismatch_raises_not_found(self, did_service_no_migrations, vault_service):
        """VC with wrong division should raise ArtefactNotFoundError (security)."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")
        vault_service.ensure_division_signing_key("advisory")

        artefact = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            )
        )

        # Should raise ArtefactNotFoundError, not DivisionMismatchError
        # This prevents leaking that the artefact exists in a different division
        with pytest.raises(ArtefactNotFoundError):
            did_service.artefact_vc("advisory", artefact.version_uid)

    def test_missing_signing_keys_raises(self, did_service_no_migrations, vault_service):
        """VC generation without signing keys should raise DivisionKeysNotFound."""
        did_service = did_service_no_migrations
        vault_service._client.clear()

        artefact = did_service.upsert_artefact(
            ArtefactInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            )
        )

        with pytest.raises(DivisionKeysNotFound):
            did_service.artefact_vc("epdw", artefact.version_uid)
