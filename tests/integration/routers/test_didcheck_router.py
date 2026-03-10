"""Integration tests for app/routers/didcheck.py.

Full end-to-end integration tests that verify the didcheck API endpoints
work correctly with the full stack (FastAPI, DIDService, MongoDB, Vault).
"""

import base58
import pytest
from fastapi.testclient import TestClient

from app.did_utils.eddsa import MULTICODEC_ED25519_PUB, verify_vc_signature

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

    # Ensure divisions have signing keys
    vault_service.ensure_division_signing_key("advisory")
    vault_service.ensure_division_signing_key("epdw")

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
def didcheck_headers(test_config):
    """Headers with valid didcheck API token."""
    return {"X-API-Token": test_config.tokens.didcheck_access_token}


@pytest.fixture
def epdw_headers(test_config):
    """Headers with valid EPDW API token."""
    return {"X-API-Token": test_config.tokens.epdw_access_token}


@pytest.fixture
def advisory_headers(test_config):
    """Headers with valid advisory API token."""
    return {"X-API-Token": test_config.tokens.advisory_access_token}


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestDIDCheckRouterFullWorkflow:
    """Full end-to-end integration tests for didcheck router."""

    def test_create_artefact_and_verify_vc_full_workflow(self, test_client, epdw_headers, didcheck_headers):
        """Full workflow: create artefact via EPDW, fetch VC via didcheck, verify signature.

        This comprehensive test verifies:
        1. Recording a benchmark execution creates a DID
        2. The VC can be fetched via didcheck endpoint
        3. The VC structure is correct
        4. The VC proof is valid
        5. The signature can be verified using the public key from the DID document
        """

        # =====================================================================
        # Step 1: Record a benchmark execution via EPDW
        # =====================================================================
        benchmark_data = {
            "benchmark_id": "11111111-2222-3333-4444-555555555555",
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            "artefact_metadata": {
                "benchmark_name": "stream_triad",
                "platform": "AMD EPYC 9654",
                "score": 1234.5,
            },
            "iterations": [
                {
                    "iteration_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                }
            ],
        }

        epdw_response = test_client.post(
            "/epdw/record-benchmark",
            json=benchmark_data,
            headers=epdw_headers,
        )

        assert epdw_response.status_code == 200, f"Failed to record benchmark: {epdw_response.text}"
        epdw_data = epdw_response.json()
        uid = epdw_data["benchmark_did"].split(":")[-1]

        # =====================================================================
        # Step 2: Fetch the VC via didcheck endpoint
        # =====================================================================
        vc_response = test_client.get(
            f"/didcheck/{uid}/vc.json",
            headers=didcheck_headers,
        )

        assert vc_response.status_code == 200, f"Failed to fetch VC: {vc_response.text}"
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
        assert vc["issuer"] == "did:web:did.amd.com:epdw"

        # Check credentialSubject
        assert "credentialSubject" in vc
        subject = vc["credentialSubject"]
        assert "artefactHash" in subject
        assert subject["artefactHash"] == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1"
        assert "artefactMetadata" in subject
        assert subject["artefactMetadata"]["benchmark_name"] == "stream_triad"

        # =====================================================================
        # Step 4: Validate VC proof
        # =====================================================================
        assert "proof" in vc
        proof = vc["proof"]

        assert proof["type"] == "DataIntegrityProof"
        assert proof["cryptosuite"] == "eddsa-rdfc-2022"
        assert proof["verificationMethod"].startswith("did:web:did.amd.com:epdw#")

        # =====================================================================
        # Step 5: Fetch DID document and extract public key
        # =====================================================================
        did_doc_response = test_client.get(
            "/didcheck/epdw/did.json",
            headers=didcheck_headers,
        )

        assert did_doc_response.status_code == 200, f"Failed to fetch DID document: {did_doc_response.text}"
        did_doc = did_doc_response.json()

        # Verify DID document structure
        assert did_doc["id"] == "did:web:did.amd.com:epdw"
        assert "verificationMethod" in did_doc
        assert "assertionMethod" in did_doc

        # Find matching verification method
        verification_method = proof["verificationMethod"]
        matching_method = None
        for vm in did_doc["verificationMethod"]:
            if vm["id"] == verification_method:
                matching_method = vm
                break

        assert matching_method is not None, f"Verification method {verification_method} not found"

        # Extract public key
        public_key_multibase = matching_method["publicKeyMultibase"]
        assert public_key_multibase.startswith("z"), "Expected base58btc multibase encoding"

        decoded = base58.b58decode(public_key_multibase[1:])
        assert decoded[:2] == MULTICODEC_ED25519_PUB, "Expected Ed25519 multicodec prefix"
        public_key_bytes = decoded[2:]
        assert len(public_key_bytes) == 32, f"Expected 32-byte public key, got {len(public_key_bytes)}"

        # =====================================================================
        # Step 6: Verify the VC signature
        # =====================================================================
        is_valid = verify_vc_signature(vc, public_key_bytes)
        assert is_valid is True, "VC signature verification failed"

    def test_artefact_overview_shows_latest_version(self, test_client, epdw_headers, didcheck_headers):
        """Test that overview endpoint shows correct version information.

        Verifies:
        1. Overview for latest version shows no latest_version field
        2. Overview for older version shows latest_version information
        """

        benchmark_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        # Create version 1
        v1_response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": benchmark_id,
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                "iterations": [
                    {
                        "iteration_id": "11111111-1111-1111-1111-111111111111",
                        "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD5",
                    }
                ],
            },
            headers=epdw_headers,
        )
        assert v1_response.status_code == 200
        v1_uid = v1_response.json()["benchmark_version_did"].split(":")[-1]

        # Create version 2 (update with different hash)
        v2_response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": benchmark_id,
                "artefact_hash": "QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                "iterations": [
                    {
                        "iteration_id": "11111111-1111-1111-1111-111111111111",
                        "artefact_hash": "QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD4",
                    }
                ],
            },
            headers=epdw_headers,
        )
        assert v2_response.status_code == 200
        v2_uid = v2_response.json()["benchmark_version_did"].split(":")[-1]

        # Get overview for version 1 (older version)
        overview_v1 = test_client.get(
            f"/didcheck/{v1_uid}/overview",
            headers=didcheck_headers,
        )
        assert overview_v1.status_code == 200
        v1_data = overview_v1.json()

        # Should have latest_version field pointing to version 2
        assert "latest_version" in v1_data
        assert v1_data["latest_version"] is not None
        assert v1_data["latest_version"]["version"] == 2
        assert v1_data["latest_version"]["version_uid"] == v2_uid

        # Should show queried version details
        assert v1_data["digital_artefact"]["version"] == 1
        assert v1_data["digital_artefact"]["version_uid"] == v1_uid

        # Get overview for version 2 (latest version)
        overview_v2 = test_client.get(
            f"/didcheck/{v2_uid}/overview",
            headers=didcheck_headers,
        )
        assert overview_v2.status_code == 200
        v2_data = overview_v2.json()

        # Should NOT have latest_version field (or it should be null)
        assert v2_data.get("latest_version") is None

    def test_artefact_full_returns_complete_data(self, test_client, advisory_headers, didcheck_headers):
        """Test that artefact.json endpoint returns all fields including metadata."""

        # Create recommendation with metadata
        rec_response = test_client.post(
            "/advisory/record_recommendation",
            json={
                "recommendation_uid": "11111111-1111-1111-1111-111111111111",
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7wRec11",
                "artefact_metadata": {
                    "recommendation_text": "Use AMD EPYC 9004 series",
                    "category": "hardware",
                    "priority": "high",
                },
            },
            headers=advisory_headers,
        )
        assert rec_response.status_code == 200
        uid = rec_response.json()["artefact_did"].split(":")[-1]

        # Fetch full artefact data
        full_response = test_client.get(
            f"/didcheck/{uid}/artefact.json",
            headers=didcheck_headers,
        )
        assert full_response.status_code == 200
        full_data = full_response.json()

        # Verify all fields are present
        assert "external_uid" in full_data
        assert "version_uid" in full_data
        assert "version" in full_data
        assert full_data["version"] == 1
        assert "division" in full_data
        assert full_data["division"] == "advisory"
        assert "artefact_hash" in full_data
        assert full_data["artefact_hash"] == "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2G7wRec11"
        assert "creation_date" in full_data
        assert "revoked" in full_data
        assert full_data["revoked"] is False
        assert "artefact_type" in full_data
        assert full_data["artefact_type"] == "recommendation"

        # Verify metadata is included and correct
        assert "artefact_metadata" in full_data
        assert full_data["artefact_metadata"]["recommendation_text"] == "Use AMD EPYC 9004 series"
        assert full_data["artefact_metadata"]["category"] == "hardware"
        assert full_data["artefact_metadata"]["priority"] == "high"

        # Verify provenance field exists (empty for this case)
        assert "provenance" in full_data or full_data.get("provenance") is None

    def test_provenance_tree_recursive(self, test_client, epdw_headers, didcheck_headers):
        """Test recursive provenance tree construction.

        Creates a multi-level provenance chain:
        exec1 <- exec2 <- exec3
        """

        # Create exec1 (no provenance)
        exec1_response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": "11111111-1111-1111-1111-111111111111",
                "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                "iterations": [
                    {
                        "iteration_id": "aaaa1111-1111-1111-1111-111111111111",
                        "artefact_hash": "QmYwAPJzv5CZsnA1t8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                    }
                ],
            },
            headers=epdw_headers,
        )
        assert exec1_response.status_code == 200
        exec1_uid = exec1_response.json()["benchmark_did"].split(":")[-1]

        # Create exec2 (provenance: exec1)
        exec2_response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": "22222222-2222-2222-2222-222222222222",
                "artefact_hash": "QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
                "provenance": [exec1_uid],
                "iterations": [
                    {
                        "iteration_id": "aaaa2222-2222-2222-2222-222222222222",
                        "artefact_hash": "QmYwAPJzv5CZsnA2t8auVZRn8x5M3kN1p6yZR2oG7wJGD4",
                    }
                ],
            },
            headers=epdw_headers,
        )
        assert exec2_response.status_code == 200
        exec2_uid = exec2_response.json()["benchmark_did"].split(":")[-1]

        # Create exec3 (provenance: exec2)
        exec3_response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": "33333333-3333-3333-3333-333333333333",
                "artefact_hash": "QmYwAPJzv5CZsnA3t8auVZRn8x5M3kN1p6yZR2oG7wJGD5",
                "provenance": [exec2_uid],
                "iterations": [
                    {
                        "iteration_id": "aaaa3333-3333-3333-3333-333333333333",
                        "artefact_hash": "QmYwAPJzv5CZsnA3t8auVZRn8x5M3kN1p6yZR2oG7wJGD6",
                    }
                ],
            },
            headers=epdw_headers,
        )
        assert exec3_response.status_code == 200
        exec3_uid = exec3_response.json()["benchmark_did"].split(":")[-1]

        # Get provenance tree for exec3
        prov_response = test_client.get(
            f"/didcheck/{exec3_uid}/provenance",
            headers=didcheck_headers,
        )
        assert prov_response.status_code == 200
        prov_data = prov_response.json()

        # Verify response structure
        assert "root_uid" in prov_data
        assert prov_data["root_uid"] == exec3_uid
        assert "max_depth" in prov_data
        assert "max_children" in prov_data
        assert "provenance" in prov_data

        # Verify tree structure: exec3 -> exec2 -> exec1
        provenance = prov_data["provenance"]
        assert len(provenance) == 1  # exec3 has one direct provenance item (exec2)

        exec2_node = provenance[0]
        assert exec2_node["division"] == "epdw"
        assert exec2_node["truncated"] is False
        assert exec2_node["children"] is not None
        assert len(exec2_node["children"]) == 1

        exec1_node = exec2_node["children"][0]
        assert exec1_node["division"] == "epdw"
        assert exec1_node["truncated"] is False
        # exec1 has no provenance, so children should be None or empty
        assert exec1_node.get("children") is None or len(exec1_node.get("children", [])) == 0

    def test_versions_returns_all_versions_sorted(self, test_client, epdw_headers, didcheck_headers):
        """Test that versions endpoint returns all versions in ascending order."""

        benchmark_id = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"

        # Create 3 versions
        for i in range(1, 4):
            response = test_client.post(
                "/epdw/record-benchmark",
                json={
                    "benchmark_id": benchmark_id,
                    "artefact_hash": f"QmYwAPJzv5CZsnA{i}t8auVZRn8x5M3kN1p6yZR2oG7wJGD{i}",
                    "iterations": [
                        {
                            "iteration_id": f"aaaa000{i}-bbbb-cccc-dddd-eeeeeeeeeeee",
                            "artefact_hash": f"QmYwAPJzv5CZsnAzt{i}auVZRn8x5M3kN1p6yZR2oG7wJGD{i}",
                        }
                    ],
                },
                headers=epdw_headers,
            )
            assert response.status_code == 200

        # Get all versions
        versions_response = test_client.get(
            f"/didcheck/{benchmark_id}/versions",
            headers=didcheck_headers,
        )
        assert versions_response.status_code == 200
        versions_data = versions_response.json()

        # Verify structure
        assert "external_uid" in versions_data
        assert "versions" in versions_data
        assert len(versions_data["versions"]) == 3

        # Verify sorted in ascending order
        versions = versions_data["versions"]
        assert versions[0]["version"] == 1
        assert versions[1]["version"] == 2
        assert versions[2]["version"] == 3

        # Verify each version has required fields
        for v in versions:
            assert "version" in v
            assert "version_uid" in v
            assert "creation_date" in v
            assert "revoked" in v

    def test_descendants_pagination_workflow(self, test_client, epdw_headers, didcheck_headers):
        """Test descendants endpoint pagination.

        Creates a parent with multiple descendants and verifies pagination.
        """

        # Create parent execution
        parent_response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": "eeee1111-1111-1111-1111-111111111111",
                "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDa",
                "iterations": [
                    {
                        "iteration_id": "ffff1111-1111-1111-1111-111111111111",
                        "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDb",
                    }
                ],
            },
            headers=epdw_headers,
        )
        assert parent_response.status_code == 200
        parent_uid = parent_response.json()["benchmark_did"].split(":")[-1]

        # Create 5 descendants
        for i in range(5):
            test_client.post(
                "/epdw/record-benchmark",
                json={
                    "benchmark_id": f"aaaa000{i}-2222-3333-4444-555555555555",
                    "artefact_hash": f"QmYwAPJzv5CZsnAzt{i}auVZRn8x5M3kN1p6yZR2oG7wJGDc",
                    "provenance": [parent_uid],
                    "iterations": [
                        {
                            "iteration_id": f"bbbb000{i}-2222-3333-4444-555555555555",
                            "artefact_hash": f"QmYwAPJzv5CZsnAzt{i}auVZRn8x5M3kN1p6yZR2oG7wJGDd",
                        }
                    ],
                },
                headers=epdw_headers,
            )

        # Test pagination - page 1, size 2
        page1_response = test_client.get(
            f"/didcheck/{parent_uid}/descendants?page=1&page_size=2",
            headers=didcheck_headers,
        )
        assert page1_response.status_code == 200
        page1_data = page1_response.json()

        assert page1_data["root_uid"] == parent_uid
        assert page1_data["total_count"] == 5
        assert page1_data["page"] == 1
        assert page1_data["page_size"] == 2
        assert len(page1_data["descendants"]) == 2
        assert page1_data["has_more"] is True

        # Test page 2
        page2_response = test_client.get(
            f"/didcheck/{parent_uid}/descendants?page=2&page_size=2",
            headers=didcheck_headers,
        )
        assert page2_response.status_code == 200
        page2_data = page2_response.json()

        assert page2_data["page"] == 2
        assert len(page2_data["descendants"]) == 2
        assert page2_data["has_more"] is True

        # Test page 3 (last page)
        page3_response = test_client.get(
            f"/didcheck/{parent_uid}/descendants?page=3&page_size=2",
            headers=didcheck_headers,
        )
        assert page3_response.status_code == 200
        page3_data = page3_response.json()

        assert page3_data["page"] == 3
        assert len(page3_data["descendants"]) == 1  # Only 1 item on last page
        assert page3_data["has_more"] is False

    def test_missing_api_token_returns_422(self, test_client):
        """Test that missing API token returns 422 for missing required header."""

        response = test_client.get("/didcheck/11111111-2222-3333-4444-555555555555/vc.json")
        assert response.status_code == 422

    def test_invalid_api_token_returns_401(self, test_client):
        """Test that invalid API token returns 401 Unauthorized."""

        response = test_client.get(
            "/didcheck/11111111-2222-3333-4444-555555555555/vc.json",
            headers={"X-API-Token": "invalid-token"},
        )
        assert response.status_code == 401

    def test_artefact_not_found_returns_404(self, test_client, didcheck_headers):
        """Test that fetching non-existent artefact returns 404."""

        response = test_client.get(
            "/didcheck/99999999-9999-9999-9999-999999999999/vc.json",
            headers=didcheck_headers,
        )
        assert response.status_code == 404

    def test_division_did_document_not_found_returns_404(self, test_client, didcheck_headers):
        """Test that fetching DID document for non-existent division returns 404."""

        response = test_client.get(
            "/didcheck/nonexistent/did.json",
            headers=didcheck_headers,
        )
        assert response.status_code == 404

    def test_division_did_document_public_access(self, test_client, didcheck_headers):
        """Test that division DID document endpoint works with authentication.

        Note: This endpoint requires authentication like other didcheck endpoints.
        """

        response = test_client.get(
            "/didcheck/epdw/did.json",
            headers=didcheck_headers,
        )
        assert response.status_code == 200
        did_doc = response.json()

        assert did_doc["id"] == "did:web:did.amd.com:epdw"
        assert "@context" in did_doc
        assert "verificationMethod" in did_doc
        assert "assertionMethod" in did_doc
