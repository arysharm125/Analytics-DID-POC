"""Unit tests for app/routers/demo_division.py."""

import pytest
from pydantic import ValidationError

from app.routers.demo_division import RecordArtefactRequest, RecordArtefactResponse

# =============================================================================
# Test RecordArtefactRequest Model
# =============================================================================


class TestRecordArtefactRequestModel:
    """Tests for RecordArtefactRequest Pydantic model validation."""

    def test_valid_request_with_all_fields(self):
        """Request with all fields should validate successfully."""
        request = RecordArtefactRequest(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_type="report",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            artefact_metadata={"filename": "test.xlsx", "service": "demo"},
            backlink="https://example.com/resource/123",
            provenance=["11111111-2222-3333-4444-555555555555"],
            update_message="Initial submission",
            updated_by="user@amd.com",
        )

        assert request.external_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert request.artefact_type == "report"
        assert request.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"
        assert request.artefact_metadata == {"filename": "test.xlsx", "service": "demo"}
        assert request.backlink == "https://example.com/resource/123"
        assert request.provenance == ["11111111-2222-3333-4444-555555555555"]
        assert request.update_message == "Initial submission"
        assert request.updated_by == "user@amd.com"

    def test_valid_request_minimal(self):
        """Request with only required fields should validate."""
        request = RecordArtefactRequest(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_type="benchmark",
        )

        assert request.external_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert request.artefact_type == "benchmark"
        assert request.artefact_hash is None
        assert request.artefact_metadata is None
        assert request.backlink is None
        assert request.provenance is None
        assert request.update_message is None
        assert request.updated_by is None

    def test_missing_external_uid_raises_error(self):
        """Request without external_uid should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            RecordArtefactRequest(
                artefact_type="report",
            ) # type: ignore

        assert "external_uid" in str(exc.value)

    def test_missing_artefact_type_raises_error(self):
        """Request without artefact_type should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            RecordArtefactRequest(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            ) # type: ignore

        assert "artefact_type" in str(exc.value)


# =============================================================================
# Test RecordArtefactResponse Model
# =============================================================================


class TestRecordArtefactResponseModel:
    """Tests for RecordArtefactResponse Pydantic model."""

    def test_response_fields(self):
        """Response should have all required fields with correct types."""
        response = RecordArtefactResponse(
            artefact_did="did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            version_did="did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
            version=1,
        )

        assert response.artefact_did == "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert response.version_did == "did:web:did.amd.com:11111111-2222-3333-4444-555555555555"
        assert response.version == 1

    def test_response_accepts_higher_versions(self):
        """Response should accept version numbers > 1."""
        response = RecordArtefactResponse(
            artefact_did="did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            version_did="did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
            version=42,
        )

        assert response.version == 42
