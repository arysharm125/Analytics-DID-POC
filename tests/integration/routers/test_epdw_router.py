"""Integration tests for app/routers/epdw.py.

Full end-to-end integration tests that verify the EPDW API endpoints
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

    # Ensure epdw division has signing keys
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
def epdw_headers(test_config):
    """Headers with valid EPDW API token."""
    return {"X-API-Token": test_config.tokens.epdw_access_token}


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestEPDWRouterFullWorkflow:
    """Full end-to-end integration tests for EPDW router."""

    def test_record_benchmark_update_and_verify_vcs_full_workflow(self, test_client, epdw_headers):
        """Full workflow: record benchmark with iterations, update some, verify all VCs.

        This comprehensive test verifies:
        1. Recording a benchmark with multiple iterations
        2. Updating benchmark and subset of iterations
        3. Generating VCs for all artefacts
        4. Verifying all VC signatures via DID document
        5. Validating parent-child provenance relationships
        """

        # =====================================================================
        # Step 1: Record a benchmark with 3 iterations
        # =====================================================================
        benchmark_data = {
            "benchmark_id": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            "artefact_metadata": {
                "name": "SPEC CPU 2017",
                "config": "base",
                "system": "EPYC 9004",
            },
            "backlink": "https://epdw.example.com/benchmarks/bench-123",
            "iterations": [
                {
                    "iteration_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                    "artefact_metadata": {"run": 1, "score": 100.0},
                },
                {
                    "iteration_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
                    "artefact_metadata": {"run": 2, "score": 101.5},
                },
                {
                    "iteration_id": "cccccccc-dddd-eeee-ffff-000000000000",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD4",
                    "artefact_metadata": {"run": 3, "score": 99.8},
                },
            ],
        }

        response = test_client.post(
            "/epdw/record-benchmark",
            json=benchmark_data,
            headers=epdw_headers,
        )

        # Verify response
        assert response.status_code == 200, f"Failed to record benchmark: {response.text}"
        response_data = response.json()

        # Verify benchmark creation
        assert "benchmark_did" in response_data
        assert "benchmark_version_did" in response_data
        assert response_data["benchmark_version"] == 1
        assert response_data["partial_failure"] is False

        benchmark_did = response_data["benchmark_did"]
        benchmark_uid = benchmark_did.split(":")[-1]

        # Verify all iterations created
        assert len(response_data["iterations"]) == 3
        for iteration in response_data["iterations"]:
            assert iteration["status"] == "created"
            assert iteration["version"] == 1
            assert iteration["error"] is None

        # =====================================================================
        # Step 2: Update benchmark and 2 of 3 iterations
        # =====================================================================
        update_data = {
            "updates": [
                # Update benchmark
                {
                    "external_uid": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD5",
                    "artefact_metadata": {
                        "name": "SPEC CPU 2017",
                        "config": "base",
                        "system": "EPYC 9004",
                        "updated": True,
                    },
                },
                # Update iteration 1
                {
                    "external_uid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD6",
                    "artefact_metadata": {"run": 1, "score": 102.0, "updated": True},
                },
                # Update iteration 2 (preserve hash)
                {
                    "external_uid": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
                    "artefact_metadata": {"run": 2, "score": 103.0, "updated": True},
                },
                # Iteration 3 NOT updated
            ]
        }

        update_response = test_client.post(
            "/epdw/update-multiple-artefacts",
            json=update_data,
            headers=epdw_headers,
        )

        assert update_response.status_code == 200, f"Failed to update artefacts: {update_response.text}"
        update_response_data = update_response.json()

        # Verify update results
        assert update_response_data["total"] == 3
        assert update_response_data["successful"] == 3
        assert update_response_data["failed"] == 0
        assert update_response_data["partial_failure"] is False

        results = update_response_data["results"]
        assert results[0]["status"] == "updated"  # benchmark
        assert results[0]["version"] == 2
        assert results[1]["status"] == "updated"  # iter-1
        assert results[1]["version"] == 2
        assert results[2]["status"] == "updated"  # iter-2
        assert results[2]["version"] == 2

        # =====================================================================
        # Step 3: Fetch DID document for EPDW division
        # =====================================================================
        did_doc_response = test_client.get("/epdw/did.json")

        assert did_doc_response.status_code == 200, f"Failed to fetch DID document: {did_doc_response.text}"
        did_doc = did_doc_response.json()

        # Verify DID document structure
        assert did_doc["id"] == "did:web:did.amd.com:epdw"
        assert "verificationMethod" in did_doc
        assert "assertionMethod" in did_doc

        # =====================================================================
        # Step 4: Generate and verify VC for benchmark
        # =====================================================================
        benchmark_vc_response = test_client.get(
            f"/epdw/{benchmark_uid}/vc.json",
            headers=epdw_headers,
        )

        assert benchmark_vc_response.status_code == 200, f"Failed to generate benchmark VC: {benchmark_vc_response.text}"
        benchmark_vc = benchmark_vc_response.json()

        # Validate VC structure
        assert benchmark_vc["@context"]
        assert "VerifiableCredential" in benchmark_vc["type"]
        assert benchmark_vc["issuer"] == "did:web:did.amd.com:epdw"
        assert "credentialSubject" in benchmark_vc

        # Verify subject data
        subject = benchmark_vc["credentialSubject"]
        assert subject["id"] == benchmark_did
        assert subject["version"] == 2  # Updated version
        assert subject["artefactHash"] == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD5"
        assert subject["artefactMetadata"]["updated"] is True

        # Verify proof structure
        assert "proof" in benchmark_vc
        proof = benchmark_vc["proof"]
        assert proof["type"] == "DataIntegrityProof"
        assert proof["cryptosuite"] == "eddsa-rdfc-2022"
        assert proof["proofPurpose"] == "assertionMethod"
        assert proof["verificationMethod"].startswith("did:web:did.amd.com:epdw#")

        # Extract and verify signature
        verification_method = proof["verificationMethod"]
        public_key_bytes = self._extract_public_key_from_did_doc(did_doc, verification_method)
        is_valid = verify_vc_signature(benchmark_vc, public_key_bytes)
        assert is_valid is True, "Benchmark VC signature verification failed"

        # =====================================================================
        # Step 5: Generate and verify VCs for all 3 iterations
        # =====================================================================
        iteration_test_cases = [
            ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", 2, "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD6", True),
            ("bbbbbbbb-cccc-dddd-eeee-ffffffffffff", 2, "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3", True),
            ("cccccccc-dddd-eeee-ffff-000000000000", 1, "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD4", False),
        ]

        for iter_uid, expected_version, expected_hash, was_updated in iteration_test_cases:
            # Generate VC
            iter_vc_response = test_client.get(
                f"/epdw/{iter_uid}/vc.json",
                headers=epdw_headers,
            )

            assert iter_vc_response.status_code == 200, f"Failed to generate VC for {iter_uid}"
            iter_vc = iter_vc_response.json()

            # Verify version
            assert iter_vc["credentialSubject"]["version"] == expected_version

            # Verify hash
            assert iter_vc["credentialSubject"]["artefactHash"] == expected_hash

            # Verify updated flag in metadata
            iter_metadata = iter_vc["credentialSubject"]["artefactMetadata"]
            if was_updated:
                assert iter_metadata.get("updated") is True
            else:
                assert "updated" not in iter_metadata

            # =====================================================================
            # Step 6: Verify provenance in iteration VCs
            # =====================================================================
            # Each iteration should have benchmark as first provenance item
            assert "provenance" in iter_vc["credentialSubject"]
            provenance = iter_vc["credentialSubject"]["provenance"]
            assert isinstance(provenance, list)
            assert len(provenance) >= 1
            # First item should be the benchmark DID
            assert provenance[0] == benchmark_did

            # Verify signature
            is_valid = verify_vc_signature(iter_vc, public_key_bytes)
            assert is_valid is True, f"Iteration {iter_uid} VC signature verification failed"

    def test_record_benchmark_creates_correct_hierarchy(self, test_client, epdw_headers):
        """Test that benchmark-iteration hierarchy is created correctly."""

        benchmark_id = "11111111-1111-1111-1111-111111111111"
        iteration_id = "22222222-2222-2222-2222-222222222222"

        # Record benchmark
        response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": benchmark_id,
                "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                "iterations": [
                    {
                        "iteration_id": iteration_id,
                        "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                    }
                ],
            },
            headers=epdw_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify benchmark DID
        benchmark_did = data["benchmark_did"]
        assert benchmark_did == f"did:web:did.amd.com:{benchmark_id}"

        # Verify iteration DID
        iteration_result = data["iterations"][0]
        iteration_did = iteration_result["iteration_did"]
        assert iteration_did == f"did:web:did.amd.com:{iteration_id}"

        # Fetch iteration VC and verify provenance
        iter_vc_response = test_client.get(
            f"/epdw/{iteration_id}/vc.json",
            headers=epdw_headers,
        )

        assert iter_vc_response.status_code == 200
        iter_vc = iter_vc_response.json()

        # Verify provenance points to parent benchmark
        provenance = iter_vc["credentialSubject"]["provenance"]
        assert provenance[0] == benchmark_did

    def test_update_unchanged_artefact_returns_unchanged_status(self, test_client, epdw_headers):
        """Test that updating with no changes returns 'unchanged' status."""

        benchmark_id = "33333333-3333-3333-3333-333333333333"

        # Create benchmark
        test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": benchmark_id,
                "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                "artefact_metadata": {"name": "Test"},
                "iterations": [
                    {"iteration_id": "44444444-4444-4444-4444-444444444444"}
                ],
            },
            headers=epdw_headers,
        )

        # Update with same data
        update_response = test_client.post(
            "/epdw/update-multiple-artefacts",
            json={
                "updates": [
                    {
                        "external_uid": benchmark_id,
                        "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                        "artefact_metadata": {"name": "Test"},
                    }
                ]
            },
            headers=epdw_headers,
        )

        assert update_response.status_code == 200
        update_data = update_response.json()

        assert update_data["results"][0]["status"] == "unchanged"
        assert update_data["results"][0]["version"] == 1

    def test_missing_api_token_returns_422(self, test_client):
        """Test that missing API token returns 422 Unprocessable Entity."""

        response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                "iterations": [{"iteration_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}],
            },
            # No headers
        )

        assert response.status_code == 422  # FastAPI returns 422 for missing required header

    def test_invalid_api_token_returns_401(self, test_client):
        """Test that invalid API token returns 401 Unauthorized."""

        response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                "iterations": [{"iteration_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}],
            },
            headers={"X-API-Token": "invalid-token"},
        )

        assert response.status_code == 401

    def test_update_nonexistent_artefact_returns_404(self, test_client, epdw_headers):
        """Test that updating non-existent artefact returns 404 Not Found."""

        response = test_client.post(
            "/epdw/update-multiple-artefacts",
            json={
                "updates": [
                    {"external_uid": "99999999-9999-9999-9999-999999999999"}
                ]
            },
            headers=epdw_headers,
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_duplicate_iteration_ids_returns_400(self, test_client, epdw_headers):
        """Test that duplicate iteration IDs return 400 Bad Request."""

        response = test_client.post(
            "/epdw/record-benchmark",
            json={
                "benchmark_id": "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                "iterations": [
                    {"iteration_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
                    {"iteration_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
                ],
            },
            headers=epdw_headers,
        )

        assert response.status_code == 400
        assert "Duplicate iteration IDs" in response.json()["detail"]

    def test_did_document_endpoint_public(self, test_client):
        """Test that DID document endpoint is publicly accessible (no auth required)."""

        response = test_client.get("/epdw/did.json")

        assert response.status_code == 200
        did_doc = response.json()

        assert did_doc["id"] == "did:web:did.amd.com:epdw"
        assert "@context" in did_doc
        assert "verificationMethod" in did_doc

    def test_vc_not_found_returns_404(self, test_client, epdw_headers):
        """Test that fetching VC for non-existent artefact returns 404 Not Found."""

        response = test_client.get(
            "/epdw/99999999-9999-9999-9999-999999999999/vc.json",
            headers=epdw_headers,
        )

        assert response.status_code == 404

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _extract_public_key_from_did_doc(self, did_doc: dict, verification_method: str) -> bytes:
        """Extract public key bytes from DID document.

        Args:
            did_doc: The DID document
            verification_method: The verification method ID (e.g., "did:web:did.amd.com:epdw#key-1")

        Returns:
            32-byte Ed25519 public key
        """
        # Find the verification method that matches
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

        return public_key_bytes

    def test_record_benchmark_idempotent_full_workflow(self, test_client, epdw_headers):
        """Test idempotent behavior: calling record-benchmark multiple times with same/different data."""

        benchmark_id = "eeeeeeee-ffff-0000-1111-222222222222"

        # =====================================================================
        # Call 1: Create benchmark with 2 iterations
        # =====================================================================
        request1 = {
            "benchmark_id": benchmark_id,
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            "artefact_metadata": {"name": "Test Benchmark", "version": 1},
            "iterations": [
                {
                    "iteration_id": "11111111-1111-1111-1111-111111111111",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                    "artefact_metadata": {"run": 1},
                },
                {
                    "iteration_id": "22222222-2222-2222-2222-222222222222",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
                    "artefact_metadata": {"run": 2},
                },
            ],
        }

        response1 = test_client.post("/epdw/record-benchmark", json=request1, headers=epdw_headers)
        assert response1.status_code == 200
        data1 = response1.json()

        assert data1["benchmark_status"] == "created"
        assert data1["benchmark_version"] == 1
        assert len(data1["iterations"]) == 2
        assert all(it["status"] == "created" for it in data1["iterations"])
        assert data1["partial_failure"] is False

        # =====================================================================
        # Call 2: Same data - should return unchanged for all
        # =====================================================================
        response2 = test_client.post("/epdw/record-benchmark", json=request1, headers=epdw_headers)
        assert response2.status_code == 200
        data2 = response2.json()

        assert data2["benchmark_status"] == "unchanged"
        assert data2["benchmark_version"] == 1  # Same version
        assert len(data2["iterations"]) == 2
        assert all(it["status"] == "unchanged" for it in data2["iterations"])
        assert all(it["version"] == 1 for it in data2["iterations"])
        assert data2["partial_failure"] is False

        # =====================================================================
        # Call 3: Add 2 new iterations (keep benchmark same)
        # =====================================================================
        request3 = {
            "benchmark_id": benchmark_id,
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",  # Same
            "artefact_metadata": {"name": "Test Benchmark", "version": 1},  # Same
            "iterations": [
                {
                    "iteration_id": "33333333-3333-3333-3333-333333333333",  # NEW
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD4",
                },
                {
                    "iteration_id": "44444444-4444-4444-4444-444444444444",  # NEW
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD5",
                },
            ],
        }

        response3 = test_client.post("/epdw/record-benchmark", json=request3, headers=epdw_headers)
        assert response3.status_code == 200
        data3 = response3.json()

        assert data3["benchmark_status"] == "unchanged"
        assert data3["benchmark_version"] == 1
        assert len(data3["iterations"]) == 2
        assert all(it["status"] == "created" for it in data3["iterations"])  # Both new
        assert data3["partial_failure"] is False

        # =====================================================================
        # Call 4: Update benchmark + mix of new/unchanged/updated iterations
        # =====================================================================
        request4 = {
            "benchmark_id": benchmark_id,
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD9",  # Changed
            "artefact_metadata": {"name": "Test Benchmark", "version": 2},  # Changed
            "iterations": [
                {
                    "iteration_id": "11111111-1111-1111-1111-111111111111",  # Existing, unchanged
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                    "artefact_metadata": {"run": 1},
                },
                {
                    "iteration_id": "22222222-2222-2222-2222-222222222222",  # Existing, updated
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD8",  # Changed
                    "artefact_metadata": {"run": 2, "updated": True},
                },
                {
                    "iteration_id": "55555555-5555-5555-5555-555555555555",  # NEW
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD6",
                },
            ],
        }

        response4 = test_client.post("/epdw/record-benchmark", json=request4, headers=epdw_headers)
        assert response4.status_code == 200
        data4 = response4.json()

        assert data4["benchmark_status"] == "updated"
        assert data4["benchmark_version"] == 2
        assert len(data4["iterations"]) == 3

        # Verify statuses
        assert data4["iterations"][0]["status"] == "unchanged"  # iter-1
        assert data4["iterations"][0]["version"] == 1
        assert data4["iterations"][1]["status"] == "updated"  # iter-2
        assert data4["iterations"][1]["version"] == 2
        assert data4["iterations"][2]["status"] == "created"  # iter-5
        assert data4["iterations"][2]["version"] == 1
        assert data4["partial_failure"] is False

    def test_add_iterations_to_existing_benchmark(self, test_client, epdw_headers):
        """Test adding new iterations to an existing benchmark execution."""

        benchmark_id = "ffffffff-0000-1111-2222-333333333333"

        # Create initial benchmark with 1 iteration
        initial_request = {
            "benchmark_id": benchmark_id,
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            "iterations": [
                {
                    "iteration_id": "aaaaaaaa-1111-1111-1111-111111111111",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                }
            ],
        }

        response1 = test_client.post("/epdw/record-benchmark", json=initial_request, headers=epdw_headers)
        assert response1.status_code == 200
        assert response1.json()["benchmark_status"] == "created"

        # Add 3 more iterations
        add_iterations_request = {
            "benchmark_id": benchmark_id,
            "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",  # Same benchmark
            "iterations": [
                {
                    "iteration_id": "bbbbbbbb-2222-2222-2222-222222222222",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
                },
                {
                    "iteration_id": "cccccccc-3333-3333-3333-333333333333",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD4",
                },
                {
                    "iteration_id": "dddddddd-4444-4444-4444-444444444444",
                    "artefact_hash": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD5",
                },
            ],
        }

        response2 = test_client.post("/epdw/record-benchmark", json=add_iterations_request, headers=epdw_headers)
        assert response2.status_code == 200
        data2 = response2.json()

        # Benchmark unchanged
        assert data2["benchmark_status"] == "unchanged"
        assert data2["benchmark_version"] == 1

        # All 3 new iterations created
        assert len(data2["iterations"]) == 3
        assert all(it["status"] == "created" for it in data2["iterations"])
        assert all(it["version"] == 1 for it in data2["iterations"])
        assert data2["partial_failure"] is False

        # Verify all iterations have correct provenance
        for iteration in data2["iterations"]:
            iter_vc = test_client.get(
                f"/epdw/{iteration['iteration_id']}/vc.json",
                headers=epdw_headers,
            ).json()
            provenance = iter_vc["credentialSubject"]["provenance"]
            assert provenance[0] == f"did:web:did.amd.com:{benchmark_id}"
