"""Unit tests for app/routers/advisory_router.py.

Tests the advisory API router-specific Pydantic models and validation.
Business logic tests for DIDService methods are in tests/unit/services/test_did_service.py.
"""

import pytest
from pydantic import ValidationError

from app.routers.advisory_router import RecordReportRequest, RecordReportResponse
from app.services.exceptions import DuplicateProvenanceError

# =============================================================================
# Test RecordReportRequest Model
# =============================================================================


class TestRecordReportRequestModel:
    """Tests for RecordReportRequest Pydantic model validation."""

    def test_valid_request_with_all_fields(self):
        """Request with all fields should validate successfully."""
        request = RecordReportRequest(
            artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            artefact_metadata={"filename": "report.xlsx", "service": "cca"},
            provenance=["11111111-2222-3333-4444-555555555555"],
        )

        assert request.artefact_id == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert request.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"
        assert request.artefact_metadata == {"filename": "report.xlsx", "service": "cca"}
        assert request.provenance == ["11111111-2222-3333-4444-555555555555"]

    def test_valid_request_minimal(self):
        """Request with only required artefact_id should validate."""
        request = RecordReportRequest(
            artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        )

        assert request.artefact_id == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert request.artefact_hash is None
        assert request.artefact_metadata is None
        assert request.provenance is None

    def test_artefact_id_accepts_valid_uuid(self):
        """Valid UUID format should be accepted for artefact_id."""
        valid_uuids = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "00000000-0000-0000-0000-000000000000",
            "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
        ]

        for uuid_str in valid_uuids:
            request = RecordReportRequest(artefact_id=uuid_str)
            assert request.artefact_id == uuid_str

    def test_artefact_id_rejects_invalid_uuid(self):
        """Invalid UUID format should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            RecordReportRequest(artefact_id="not-a-valid-uuid")

        assert "artefact_id" in str(exc.value)

    def test_artefact_id_rejects_partial_uuid(self):
        """Partial UUID should raise ValidationError."""
        with pytest.raises(ValidationError):
            RecordReportRequest(artefact_id="95da4dd5-6e48-4c5b")

    def test_artefact_hash_accepts_valid_multihash(self):
        """Valid multihash should be accepted."""
        request = RecordReportRequest(
            artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
        )

        assert request.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"

    def test_artefact_hash_rejects_invalid_multihash(self):
        """Invalid multihash should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            RecordReportRequest(
                artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                artefact_hash="InvalidHash",
            )

        assert "artefact_hash" in str(exc.value)

    def test_artefact_hash_rejects_wrong_prefix(self):
        """Multihash with wrong prefix should raise ValidationError."""
        with pytest.raises(ValidationError):
            RecordReportRequest(
                artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                artefact_hash="XmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            )

    def test_artefact_metadata_accepts_dict(self):
        """Dict metadata should be accepted."""
        metadata = {
            "filename": "report.xlsx",
            "service": "cca",
            "nested": {"key": "value"},
        }
        request = RecordReportRequest(
            artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_metadata=metadata,
        )

        assert request.artefact_metadata == metadata

    def test_artefact_metadata_accepts_empty_dict(self):
        """Empty dict metadata should be accepted."""
        request = RecordReportRequest(
            artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_metadata={},
        )

        assert request.artefact_metadata == {}

    def test_provenance_accepts_uuid_list(self):
        """List of UUIDs should be accepted."""
        provenance = [
            "11111111-2222-3333-4444-555555555555",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ]
        request = RecordReportRequest(
            artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            provenance=provenance,
        )

        assert request.provenance == provenance

    def test_provenance_accepts_did_list(self):
        """List of DIDs should be canonicalized to UUIDs."""
        request = RecordReportRequest(
            artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            provenance=[
                "did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
                "did:web:did.amd.com:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            ],
        )

        # DIDs should be canonicalized to UUIDs
        assert request.provenance == [
            "11111111-2222-3333-4444-555555555555",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ]

    def test_provenance_accepts_mixed_list(self):
        """Mixed list of DIDs and UUIDs should be canonicalized."""
        request = RecordReportRequest(
            artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            provenance=[
                "11111111-2222-3333-4444-555555555555",
                "did:web:did.amd.com:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            ],
        )

        assert request.provenance == [
            "11111111-2222-3333-4444-555555555555",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ]

    def test_provenance_rejects_duplicates(self):
        """Duplicate provenance items should raise DuplicateProvenanceError."""
        with pytest.raises(DuplicateProvenanceError) as exc:
            RecordReportRequest(
                artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                provenance=[
                    "11111111-2222-3333-4444-555555555555",
                    "11111111-2222-3333-4444-555555555555",
                ],
            )

        # Should contain DuplicateProvenanceError message
        assert "Duplicate" in str(exc.value)

    def test_provenance_rejects_duplicates_after_canonicalization(self):
        """Duplicates after DID canonicalization should raise DuplicateProvenanceError."""
        with pytest.raises(DuplicateProvenanceError):
            RecordReportRequest(
                artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                provenance=[
                    "11111111-2222-3333-4444-555555555555",
                    "did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
                ],
            )

    def test_provenance_accepts_empty_list(self):
        """Empty provenance list should be accepted."""
        request = RecordReportRequest(
            artefact_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            provenance=[],
        )

        assert request.provenance == []


# =============================================================================
# Test RecordReportResponse Model
# =============================================================================


class TestRecordReportResponseModel:
    """Tests for RecordReportResponse Pydantic model."""

    def test_response_fields(self):
        """Response should have all required fields with correct types."""
        response = RecordReportResponse(
            artefact_did="did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            version_did="did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
            version=1,
        )

        assert response.artefact_did == "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert response.version_did == "did:web:did.amd.com:11111111-2222-3333-4444-555555555555"
        assert response.version == 1

    def test_response_accepts_higher_versions(self):
        """Response should accept version numbers > 1."""
        response = RecordReportResponse(
            artefact_did="did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            version_did="did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
            version=42,
        )

        assert response.version == 42
