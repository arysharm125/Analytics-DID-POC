"""Integration tests for app/routers/demo_division.py.

Full end-to-end integration tests that verify the demo division API endpoints
work correctly with the full stack (FastAPI, DIDService, MongoDB, Vault).
"""

import pytest
from fastapi.testclient import TestClient

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def test_client(db_connector, vault_service, override_test_config):
    """Create FastAPI TestClient with injected dependencies.

    This fixture sets up a full FastAPI application with test dependencies
    injected, allowing end-to-end testing of the API.
    """
    from app.main import app
    from app.routers.dependencies import set_db_dependency, set_vault_dependency
    from app.services.did_service import DIDService

    # Inject test dependencies
    set_db_dependency(db_connector)
    set_vault_dependency(vault_service)

    # Ensure demodivision division has signing keys
    vault_service.ensure_division_signing_key("demodivision")

    # Create and inject DIDService with test dependencies
    did_service = DIDService(
        db=db_connector,
        vault_svc=vault_service,
        run_migrations=True,
        ensure_signing_keys=False,  # Already done above
    )

    from app.routers.dependencies import set_did_service_dependency
    set_did_service_dependency(did_service)

    # Create test client
    return TestClient(app)


@pytest.fixture
def demodiv_headers(test_config):
    """Headers with valid demo division API token."""
    return {"X-API-Token": test_config.tokens.demodiv_access_token}


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestDemoDivisionRouterFullWorkflow:
    """Full end-to-end integration tests for demo division router."""

    def test_record_artefact_full_workflow(self, test_client, demodiv_headers):
        """Full workflow: create artefact, verify response structure and DID format.

        This comprehensive test verifies:
        1. Recording a demo division artefact creates a DID
        2. The response structure is correct
        3. The DID format is valid
        4. A VC can be generated for the artefact
        """

        # =====================================================================
        # Step 1: Record a demo division artefact
        # =====================================================================
        artefact_data = {
            "external_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "artefact_type": "report",
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            "artefact_metadata": {
                "filename": "demo-test.xlsx",
                "category": "testing",
            },
        }

        response = test_client.post(
            "/demodivision/record_artefact",
            json=artefact_data,
            headers=demodiv_headers,
        )

        # Verify response
        assert response.status_code == 200, f"Failed to record artefact: {response.text}"
        response_data = response.json()

        # Verify response structure
        assert "artefact_did" in response_data
        assert "version_did" in response_data
        assert "version" in response_data
        assert response_data["version"] == 1

        # Extract UIDs for later use
        artefact_did = response_data["artefact_did"]
        version_did = response_data["version_did"]

        # Verify DID format
        assert artefact_did.startswith("did:web:did.amd.com:")
        assert version_did.startswith("did:web:did.amd.com:")

        # Extract UUID from DID for VC endpoint
        uid = artefact_did.split(":")[-1]
        assert uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        # =====================================================================
        # Step 2: Generate a Verifiable Credential
        # =====================================================================
        vc_response = test_client.get(
            f"/demodivision/{uid}/vc.json",
            headers=demodiv_headers,
        )

        assert vc_response.status_code == 200, f"Failed to generate VC: {vc_response.text}"
        vc = vc_response.json()

        # =====================================================================
        # Step 3: Validate VC structure
        # =====================================================================

        # Check issuer is demodivision
        assert "issuer" in vc
        assert vc["issuer"] == "did:web:did.amd.com:demodivision"

        # Check credentialSubject
        assert "credentialSubject" in vc
        subject = vc["credentialSubject"]

        # Verify subject contains artefact data
        assert subject["id"] == artefact_did
        assert subject["version"] == 1
        assert subject["versionUid"] == version_did

        # Verify artefact_hash is included
        assert "artefactHash" in subject
        assert subject["artefactHash"] == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"

        # Verify artefact_metadata is included
        assert "artefactMetadata" in subject
        assert subject["artefactMetadata"] == {
            "filename": "demo-test.xlsx",
            "category": "testing",
        }

        # Verify artefact_type is included
        assert "artefactType" in subject
        assert subject["artefactType"] == "report"

    def test_record_artefact_and_update_creates_new_version(self, test_client, demodiv_headers):
        """Test that updating an artefact creates a new version."""

        artefact_uid = "11111111-2222-3333-4444-555555555555"

        # Create first version
        response1 = test_client.post(
            "/demodivision/record_artefact",
            json={
                "external_uid": artefact_uid,
                "artefact_type": "benchmark",
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            },
            headers=demodiv_headers,
        )

        assert response1.status_code == 200
        v1_data = response1.json()
        assert v1_data["version"] == 1

        # Update with new hash (creates version 2)
        response2 = test_client.post(
            "/demodivision/record_artefact",
            json={
                "external_uid": artefact_uid,
                "artefact_type": "benchmark",
                "artefact_hash": "QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
            },
            headers=demodiv_headers,
        )

        assert response2.status_code == 200
        v2_data = response2.json()
        assert v2_data["version"] == 2

        # artefact_did should be the same
        assert v1_data["artefact_did"] == v2_data["artefact_did"]

        # version_did should be different
        assert v1_data["version_did"] != v2_data["version_did"]

    def test_missing_api_token_returns_422(self, test_client):
        """Test that missing API token returns 422 for missing required header."""

        response = test_client.post(
            "/demodivision/record_artefact",
            json={
                "external_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                "artefact_type": "report",
            },
            # No headers
        )

        assert response.status_code == 422  # FastAPI returns 422 for missing required header

    def test_invalid_api_token_returns_401(self, test_client):
        """Test that invalid API token returns 401 Unauthorized."""

        response = test_client.post(
            "/demodivision/record_artefact",
            json={
                "external_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                "artefact_type": "report",
            },
            headers={"X-API-Token": "invalid-token"},
        )

        assert response.status_code == 401

    def test_no_changes_returns_400(self, test_client, demodiv_headers):
        """Test that upserting with no changes returns 400 Bad Request."""

        artefact_uid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        # Create first version
        test_client.post(
            "/demodivision/record_artefact",
            json={
                "external_uid": artefact_uid,
                "artefact_type": "test_data",
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            },
            headers=demodiv_headers,
        )

        # Try to create with same data
        response = test_client.post(
            "/demodivision/record_artefact",
            json={
                "external_uid": artefact_uid,
                "artefact_type": "test_data",
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            },
            headers=demodiv_headers,
        )

        assert response.status_code == 400
        assert "No changes detected" in response.json()["detail"]

    def test_artefact_not_found_returns_404(self, test_client, demodiv_headers):
        """Test that fetching VC for non-existent artefact returns 404 Not Found."""

        response = test_client.get(
            "/demodivision/99999999-9999-9999-9999-999999999999/vc.json",
            headers=demodiv_headers,
        )

        assert response.status_code == 404

    def test_did_document_endpoint_public(self, test_client):
        """Test that DID document endpoint is publicly accessible (no auth required)."""

        response = test_client.get("/demodivision/did.json")

        assert response.status_code == 200
        did_doc = response.json()

        assert did_doc["id"] == "did:web:did.amd.com:demodivision"
        assert "@context" in did_doc
        assert "verificationMethod" in did_doc
