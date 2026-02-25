"""Unit tests for app/routers/generic_did_router.py.

Tests the generic DID router endpoints including the debug VC N-Quads endpoint.
"""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import AppConfig, FeatureFlags, override_config
from app.main import app
from app.routers.dependencies import set_did_service_dependency


# =============================================================================
# Test VC N-Quads Debug Endpoint
# =============================================================================


class TestArtefactVCNquads:
    """Tests for the /{uid}/vc.nq debug endpoint."""

    @pytest.fixture
    def test_artefact_uid(self, did_service_no_migrations, sample_uuid, sample_multihash):
        """Create a test artefact and return its version UID."""
        from app.services.did_service import ArtefactInput

        result = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid,
                division="epdw",
                artefact_hash=sample_multihash,
                artefact_metadata={"test": "data"},
                artefact_type="report",
            )
        )
        return result.version_uid

    @pytest.fixture
    def client_with_service(self, did_service_no_migrations, vault_service, override_test_config):
        """Create a test client with DIDService dependency override."""
        set_did_service_dependency(did_service_no_migrations)
        vault_service.ensure_division_signing_key("epdw")
        return TestClient(app)

    def test_returns_text_plain_content_type(
        self, client_with_service, test_artefact_uid
    ):
        """Endpoint should return text/plain content type."""
        response = client_with_service.get(f"/did/{test_artefact_uid}/vc.nq")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"

    def test_returns_nquads_format(self, client_with_service, test_artefact_uid):
        """Endpoint should return N-Quads formatted text."""
        response = client_with_service.get(f"/did/{test_artefact_uid}/vc.nq")

        assert response.status_code == 200
        nquads = response.text

        # N-Quads should be non-empty string
        assert isinstance(nquads, str)
        assert len(nquads) > 0

        # N-Quads should contain RDF triples (ending with .)
        assert "." in nquads

        # Should contain VC-related terms
        assert "VerifiableCredential" in nquads or "verifiableCredential" in nquads

    def test_excludes_proof_from_canonicalization(
        self, client_with_service, test_artefact_uid
    ):
        """The canonicalized output should not contain proof information."""
        response = client_with_service.get(f"/did/{test_artefact_uid}/vc.nq")

        assert response.status_code == 200
        nquads = response.text

        # Proof-related terms should not appear in canonicalized output
        assert "proofValue" not in nquads
        assert "proofPurpose" not in nquads

    def test_output_is_deterministic(self, client_with_service, test_artefact_uid):
        """Same VC should produce identical N-Quads output."""
        response1 = client_with_service.get(f"/did/{test_artefact_uid}/vc.nq")
        response2 = client_with_service.get(f"/did/{test_artefact_uid}/vc.nq")

        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.text == response2.text

    def test_returns_404_when_artefact_not_found(
        self, client_with_service, sample_uuid_2
    ):
        """Endpoint should return 404 for non-existent artefact."""
        # Use a UUID that doesn't exist
        response = client_with_service.get(f"/did/{sample_uuid_2}/vc.nq")

        assert response.status_code == 404

    def test_returns_404_when_feature_flag_disabled(
        self, did_service_no_migrations, test_artefact_uid, test_config
    ):
        """Endpoint should return 404 when FEATURE_DEBUG_VC_NQUADS is disabled."""
        # Create config with debug flag disabled
        config_disabled = AppConfig(
            vault=test_config.vault,
            tokens=test_config.tokens,
            collections=test_config.collections,
            features=FeatureFlags(
                generic_did_router=True,
                debug_vc_nquads=False,  # Disabled
            ),
        )

        override_config(config_disabled)
        set_did_service_dependency(did_service_no_migrations)
        client = TestClient(app)

        response = client.get(f"/did/{test_artefact_uid}/vc.nq")

        assert response.status_code == 404
        assert "not enabled" in response.json()["detail"]

    def test_contains_credentialsubject_data(
        self, client_with_service, test_artefact_uid
    ):
        """N-Quads should contain credential subject information."""
        response = client_with_service.get(f"/did/{test_artefact_uid}/vc.nq")

        assert response.status_code == 200
        nquads = response.text

        # Should contain credential subject related data
        # The exact format depends on canonicalization, but UID should appear
        assert test_artefact_uid in nquads

    def test_multiple_artefacts_produce_different_output(
        self, client_with_service, did_service_no_migrations, sample_uuid, sample_uuid_2
    ):
        """Different artefacts should produce different N-Quads."""
        from app.services.did_service import ArtefactInput

        # Create two different artefacts
        result1 = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid,
                division="epdw",
                artefact_metadata={"test": "data1"},
                artefact_type="report",
            )
        )

        result2 = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid_2,
                division="epdw",
                artefact_metadata={"test": "data2"},
                artefact_type="benchmark",
            )
        )

        response1 = client_with_service.get(f"/did/{result1.version_uid}/vc.nq")
        response2 = client_with_service.get(f"/did/{result2.version_uid}/vc.nq")

        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.text != response2.text
