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
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            artefact_metadata={"filename": "report.xlsx", "service": "cca"},
        )

        assert request.report_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert request.recommendation_uid == "11111111-2222-3333-4444-555555555555"
        assert request.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"
        assert request.artefact_metadata == {"filename": "report.xlsx", "service": "cca"}

    def test_valid_request_minimal(self):
        """Request with only required fields should validate."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
        )

        assert request.report_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert request.recommendation_uid == "11111111-2222-3333-4444-555555555555"
        assert request.artefact_hash is None
        assert request.artefact_metadata is None

    def test_report_uid_accepts_valid_uuid(self):
        """Valid UUID format should be accepted for report_uid."""
        valid_uuids = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "00000000-0000-0000-0000-000000000000",
            "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
        ]

        for uuid_str in valid_uuids:
            request = RecordReportRequest(
                report_uid=uuid_str,
                recommendation_uid="11111111-2222-3333-4444-555555555555",
            )
            assert request.report_uid == uuid_str

    def test_report_uid_rejects_invalid_uuid(self):
        """Invalid UUID format should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            RecordReportRequest(
                report_uid="not-a-valid-uuid",
                recommendation_uid="11111111-2222-3333-4444-555555555555",
            )

        assert "report_uid" in str(exc.value)

    def test_report_uid_rejects_partial_uuid(self):
        """Partial UUID should raise ValidationError."""
        with pytest.raises(ValidationError):
            RecordReportRequest(
                report_uid="95da4dd5-6e48-4c5b",
                recommendation_uid="11111111-2222-3333-4444-555555555555",
            )

    def test_recommendation_uid_accepts_valid_uuid(self):
        """Valid UUID format should be accepted for recommendation_uid."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
        )

        assert request.recommendation_uid == "11111111-2222-3333-4444-555555555555"

    def test_recommendation_uid_accepts_did(self):
        """DID format should be accepted and canonicalized for recommendation_uid."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
        )

        # Should be canonicalized to UUID
        assert request.recommendation_uid == "11111111-2222-3333-4444-555555555555"

    def test_artefact_hash_accepts_valid_multihash(self):
        """Valid multihash should be accepted."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
        )

        assert request.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"

    def test_artefact_hash_rejects_invalid_multihash(self):
        """Invalid multihash should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            RecordReportRequest(
                report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                recommendation_uid="11111111-2222-3333-4444-555555555555",
                artefact_hash="InvalidHash",
            )

        assert "artefact_hash" in str(exc.value)

    def test_artefact_hash_rejects_wrong_prefix(self):
        """Multihash with wrong prefix should raise ValidationError."""
        with pytest.raises(ValidationError):
            RecordReportRequest(
                report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                recommendation_uid="11111111-2222-3333-4444-555555555555",
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
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
            artefact_metadata=metadata,
        )

        assert request.artefact_metadata == metadata

    def test_artefact_metadata_accepts_empty_dict(self):
        """Empty dict metadata should be accepted."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
            artefact_metadata={},
        )

        assert request.artefact_metadata == {}

    def test_update_message_accepts_string(self):
        """Valid update message should be accepted."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
            update_message="Initial report submission",
        )

        assert request.update_message == "Initial report submission"

    def test_update_message_accepts_none(self):
        """None for update_message should be accepted."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
            update_message=None,
        )

        assert request.update_message is None

    def test_updated_by_accepts_amd_email(self):
        """Valid AMD email should be accepted for updated_by."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
            updated_by="user@amd.com",
        )

        assert request.updated_by == "user@amd.com"

    def test_updated_by_accepts_none(self):
        """None for updated_by should be accepted."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
            updated_by=None,
        )

        assert request.updated_by is None

    def test_updated_by_rejects_non_amd_email(self):
        """Non-AMD email should raise InvalidUpdaterEmailError."""
        from app.services.exceptions import InvalidUpdaterEmailError

        with pytest.raises(InvalidUpdaterEmailError):
            RecordReportRequest(
                report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                recommendation_uid="11111111-2222-3333-4444-555555555555",
                updated_by="user@example.com",
            )

    def test_updated_by_rejects_invalid_email_format(self):
        """Invalid email format should raise InvalidUpdaterEmailError."""
        from app.services.exceptions import InvalidUpdaterEmailError

        with pytest.raises(InvalidUpdaterEmailError):
            RecordReportRequest(
                report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                recommendation_uid="11111111-2222-3333-4444-555555555555",
                updated_by="not-an-email",
            )

    def test_updated_by_case_insensitive(self):
        """AMD email check should be case-insensitive."""
        request = RecordReportRequest(
            report_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            recommendation_uid="11111111-2222-3333-4444-555555555555",
            updated_by="USER@AMD.COM",
        )

        assert request.updated_by == "USER@AMD.COM"


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
