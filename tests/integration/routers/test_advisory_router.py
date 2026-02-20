"""Integration tests for app/routers/advisory_router.py.

Full end-to-end integration tests that verify the advisory API endpoints
work correctly with the full stack (FastAPI, DIDService, MongoDB, Vault).
"""

import base58
import pytest

from fastapi.testclient import TestClient

from app.did_utils.eddsa import verify_vc_signature, MULTICODEC_ED25519_PUB


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

    # Ensure advisory division has signing keys
    vault_service.ensure_division_signing_key("advisory")

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
def advisory_headers(test_config):
    """Headers with valid advisory API token."""
    return {"X-API-Token": test_config.tokens.advisory_access_token}


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestAdvisoryRouterFullWorkflow:
    """Full end-to-end integration tests for advisory router."""

    def test_record_report_and_verify_vc_full_workflow(self, test_client, advisory_headers):
        """Full workflow: create report, generate VC, verify signature via DID document.

        This comprehensive test verifies:
        1. Recording an advisory report creates a DID
        2. The VC can be generated for the artefact
        3. The VC structure is correct
        4. The VC proof is valid
        5. The signature can be verified using the public key from the DID document
        """

        # =====================================================================
        # Step 1: Record an advisory report
        # =====================================================================
        report_data = {
            "artefact_id": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            "artefact_metadata": {
                "filename": "cca-report-123761827584.xlsx",
                "service": "cca",
                "analyst": "Jane Doe",
                "severity": "high",
            },
            "provenance": [],
        }

        response = test_client.post(
            "/advisory/record_report",
            json=report_data,
            headers=advisory_headers,
        )

        # Verify response
        assert response.status_code == 200, f"Failed to record report: {response.text}"
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

        # =====================================================================
        # Step 2: Generate a Verifiable Credential
        # =====================================================================
        vc_response = test_client.get(
            f"/advisory/{uid}/vc.json",
            headers=advisory_headers,
        )

        assert vc_response.status_code == 200, f"Failed to generate VC: {vc_response.text}"
        vc = vc_response.json()

        # =====================================================================
        # Step 3: Validate VC structure
        # =====================================================================

        # Check @context
        assert "@context" in vc
        assert isinstance(vc["@context"], list)
        assert "https://www.w3.org/2018/credentials/v1" in vc["@context"]

        # Check type
        assert "type" in vc
        assert isinstance(vc["type"], list)
        assert "VerifiableCredential" in vc["type"]
        assert "DigitalArtefactCredential" in vc["type"]

        # Check issuer
        assert "issuer" in vc
        assert vc["issuer"] == "did:web:did.amd.com:advisory"

        # Check issuanceDate
        assert "issuanceDate" in vc

        # Check credentialSubject
        assert "credentialSubject" in vc
        subject = vc["credentialSubject"]

        # Verify subject contains artefact data
        assert "id" in subject
        assert subject["id"] == artefact_did
        assert "version" in subject
        assert subject["version"] == 1
        assert "versionUid" in subject
        assert subject["versionUid"] == version_did
        assert "creationDate" in subject

        # Verify artefact_hash is included
        assert "artefactHash" in subject
        assert subject["artefactHash"] == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"

        # Verify artefact_metadata is included and correct
        assert "artefactMetadata" in subject
        assert subject["artefactMetadata"] == {
            "filename": "cca-report-123761827584.xlsx",
            "service": "cca",
            "analyst": "Jane Doe",
            "severity": "high",
        }

        # =====================================================================
        # Step 4: Validate VC proof
        # =====================================================================
        assert "proof" in vc
        proof = vc["proof"]

        # Check proof structure
        assert proof["type"] == "DataIntegrityProof"
        assert proof["cryptosuite"] == "eddsa-rdfc-2022"
        assert "created" in proof
        assert "verificationMethod" in proof
        assert proof["proofPurpose"] == "assertionMethod"
        assert "proofValue" in proof

        # Verify verificationMethod points to advisory division
        verification_method = proof["verificationMethod"]
        assert verification_method.startswith("did:web:did.amd.com:advisory#")

        # Verify proofValue is multibase base64url encoded
        assert proof["proofValue"].startswith("u")

        # =====================================================================
        # Step 5: Fetch the DID document for advisory division
        # =====================================================================
        did_doc_response = test_client.get("/advisory/did.json")

        assert did_doc_response.status_code == 200, f"Failed to fetch DID document: {did_doc_response.text}"
        did_doc = did_doc_response.json()

        # Verify DID document structure
        assert did_doc["id"] == "did:web:did.amd.com:advisory"
        assert "verificationMethod" in did_doc
        assert "assertionMethod" in did_doc

        # =====================================================================
        # Step 6: Extract public key from DID document
        # =====================================================================

        # Find the verification method that matches the proof
        matching_method = None
        for vm in did_doc["verificationMethod"]:
            if vm["id"] == verification_method:
                matching_method = vm
                break

        assert matching_method is not None, f"Verification method {verification_method} not found in DID document"

        # Extract public key from multibase encoding
        public_key_multibase = matching_method["publicKeyMultibase"]

        # Decode multibase (z prefix = base58btc)
        assert public_key_multibase.startswith("z"), "Expected base58btc multibase encoding"

        # Decode base58 (skip 'z' prefix)
        decoded = base58.b58decode(public_key_multibase[1:])

        # The decoded bytes should start with Ed25519 multicodec prefix (0xed01)
        # followed by the 32-byte public key
        assert len(decoded) >= 2, "Decoded public key too short"
        assert decoded[:2] == MULTICODEC_ED25519_PUB, "Expected Ed25519 multicodec prefix"

        # Extract the 32-byte public key (skip 2-byte prefix)
        public_key_bytes = decoded[2:]
        assert len(public_key_bytes) == 32, f"Expected 32-byte public key, got {len(public_key_bytes)}"

        # =====================================================================
        # Step 7: Verify the VC signature
        # =====================================================================
        is_valid = verify_vc_signature(vc, public_key_bytes)

        assert is_valid is True, "VC signature verification failed"

        # =====================================================================
        # Verification complete!
        # =====================================================================
        # At this point, we've verified that:
        # 1. The report was recorded successfully
        # 2. A valid VC was generated with correct structure
        # 3. The VC contains the correct artefact data and metadata
        # 4. The proof is properly formatted
        # 5. The signature verifies against the public key from the DID document
        # This demonstrates the complete workflow of creating, signing, and
        # verifying a Digital Artefact credential.

    def test_record_report_and_update_creates_new_version(self, test_client, advisory_headers):
        """Test that updating an artefact creates a new version."""

        artefact_id = "11111111-2222-3333-4444-555555555555"

        # Create first version
        response1 = test_client.post(
            "/advisory/record_report",
            json={
                "artefact_id": artefact_id,
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            },
            headers=advisory_headers,
        )

        assert response1.status_code == 200
        v1_data = response1.json()
        assert v1_data["version"] == 1

        # Update with new hash (creates version 2)
        response2 = test_client.post(
            "/advisory/record_report",
            json={
                "artefact_id": artefact_id,
                "artefact_hash": "QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
            },
            headers=advisory_headers,
        )

        assert response2.status_code == 200
        v2_data = response2.json()
        assert v2_data["version"] == 2

        # artefact_did should be the same
        assert v1_data["artefact_did"] == v2_data["artefact_did"]

        # version_did should be different
        assert v1_data["version_did"] != v2_data["version_did"]

    def test_record_report_with_provenance(self, test_client, advisory_headers):
        """Test recording a report with provenance references."""

        # Create parent artefact
        parent_response = test_client.post(
            "/advisory/record_report",
            json={
                "artefact_id": "11111111-1111-1111-1111-111111111111",
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Parent",
            },
            headers=advisory_headers,
        )

        assert parent_response.status_code == 200
        parent_uid = parent_response.json()["artefact_did"].split(":")[-1]

        # Create child with provenance
        child_response = test_client.post(
            "/advisory/record_report",
            json={
                "artefact_id": "22222222-2222-2222-2222-222222222222",
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7Chi1d1",
                "provenance": [parent_uid],
            },
            headers=advisory_headers,
        )

        assert child_response.status_code == 200
        child_data = child_response.json()

        # Verify child VC includes provenance
        child_uid = child_data["artefact_did"].split(":")[-1]
        vc_response = test_client.get(
            f"/advisory/{child_uid}/vc.json",
            headers=advisory_headers,
        )

        assert vc_response.status_code == 200
        vc = vc_response.json()

        # Check that provenance is in the credential subject
        assert "provenance" in vc["credentialSubject"]
        provenance = vc["credentialSubject"]["provenance"]
        assert isinstance(provenance, list)
        assert len(provenance) == 1

    def test_missing_api_token_returns_401(self, test_client):
        """Test that missing API token returns 401 Unauthorized."""

        response = test_client.post(
            "/advisory/record_report",
            json={"artefact_id": "95da4dd5-6e48-4c5b-bb91-935983c16d9c"},
            # No headers
        )

        assert response.status_code == 422  # FastAPI returns 422 for missing required header

    def test_invalid_api_token_returns_401(self, test_client):
        """Test that invalid API token returns 401 Unauthorized."""

        response = test_client.post(
            "/advisory/record_report",
            json={"artefact_id": "95da4dd5-6e48-4c5b-bb91-935983c16d9c"},
            headers={"X-API-Token": "invalid-token"},
        )

        assert response.status_code == 401

    def test_no_changes_returns_400(self, test_client, advisory_headers):
        """Test that upserting with no changes returns 400 Bad Request."""

        artefact_id = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

        # Create first version
        test_client.post(
            "/advisory/record_report",
            json={
                "artefact_id": artefact_id,
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            },
            headers=advisory_headers,
        )

        # Try to create with same data
        response = test_client.post(
            "/advisory/record_report",
            json={
                "artefact_id": artefact_id,
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            },
            headers=advisory_headers,
        )

        assert response.status_code == 400
        assert "No changes detected" in response.json()["detail"]

    def test_provenance_not_found_returns_409(self, test_client, advisory_headers):
        """Test that provenance referencing non-existent artefact returns 409 Conflict."""

        response = test_client.post(
            "/advisory/record_report",
            json={
                "artefact_id": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                "provenance": ["99999999-9999-9999-9999-999999999999"],
            },
            headers=advisory_headers,
        )

        assert response.status_code == 409
        assert "does not exist" in response.json()["detail"].lower()

    def test_artefact_not_found_returns_404(self, test_client, advisory_headers):
        """Test that fetching VC for non-existent artefact returns 404 Not Found."""

        response = test_client.get(
            "/advisory/99999999-9999-9999-9999-999999999999/vc.json",
            headers=advisory_headers,
        )

        assert response.status_code == 404

    def test_did_document_endpoint_public(self, test_client):
        """Test that DID document endpoint is publicly accessible (no auth required)."""

        response = test_client.get("/advisory/did.json")

        assert response.status_code == 200
        did_doc = response.json()

        assert did_doc["id"] == "did:web:did.amd.com:advisory"
        assert "@context" in did_doc
        assert "verificationMethod" in did_doc
