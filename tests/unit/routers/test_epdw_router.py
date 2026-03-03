"""Unit tests for app/routers/epdw.py endpoints.

Tests the /epdw/record-benchmark and /epdw/update-multiple-artefacts routes
including Pydantic model validation and route logic.
"""

import pytest
from pydantic import ValidationError

from app.routers.epdw import (
    ArtefactUpdateInput,
    BenchmarkIterationInput,
    RecordBenchmarkRequest,
    UpdateMultipleArtefactsRequest,
)
from app.services.exceptions import (
    ArtefactsNotFoundError,
    DuplicateExternalUidsError,
    DuplicateIterationIdsError,
    DuplicateProvenanceError,
    IterationIdMatchesBenchmarkIdError,
    ProvenanceNotFoundError,
)

# =============================================================================
# RecordBenchmarkRequest Model Validation Tests
# =============================================================================


class TestRecordBenchmarkRequestModel:
    """Tests for RecordBenchmarkRequest Pydantic model validation."""

    def test_valid_request_with_all_fields(self):
        """Request with all fields populated should validate successfully."""
        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            artefact_metadata={"name": "SPEC CPU 2017", "config": "base"},
            backlink="https://epdw.example.com/benchmarks/bench-123",
            provenance=["11111111-2222-3333-4444-555555555555"],
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                    artefact_metadata={"run": 1, "score": 123.45},
                    backlink="https://epdw.example.com/iterations/iter-1",
                    provenance=["22222222-3333-4444-5555-666666666666"],
                )
            ],
        )

        assert request.benchmark_id == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert request.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"
        assert request.artefact_metadata == {"name": "SPEC CPU 2017", "config": "base"}
        assert request.backlink == "https://epdw.example.com/benchmarks/bench-123"
        assert len(request.iterations) == 1

    def test_valid_request_minimal(self):
        """Request with only required fields should validate."""
        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            iterations=[
                BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
            ],
        )

        assert request.benchmark_id == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert request.artefact_hash is None
        assert request.artefact_metadata is None
        assert request.provenance is None
        assert len(request.iterations) == 1

    def test_benchmark_id_validates_uuid(self):
        """Valid UUID format should be accepted for benchmark_id."""
        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            iterations=[BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
        )
        assert request.benchmark_id == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

    def test_benchmark_id_rejects_invalid_uuid(self):
        """Invalid UUID format should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            RecordBenchmarkRequest(
                benchmark_id="not-a-valid-uuid",
                iterations=[BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
            )
        assert "benchmark_id" in str(exc.value)

    def test_artefact_hash_validates_multihash(self):
        """Valid multihash should be accepted."""
        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            iterations=[BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
        )
        assert request.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"

    def test_artefact_hash_rejects_invalid_multihash(self):
        """Invalid multihash should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            RecordBenchmarkRequest(
                benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                artefact_hash="InvalidHash",
                iterations=[BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
            )
        assert "artefact_hash" in str(exc.value)

    def test_iterations_rejects_empty_list(self):
        """Empty iterations list should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            RecordBenchmarkRequest(
                benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                iterations=[],
            )
        assert "At least one iteration is required" in str(exc.value)

    def test_iterations_accepts_single_iteration(self):
        """Single iteration should be valid."""
        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            iterations=[BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
        )
        assert len(request.iterations) == 1

    def test_iterations_accepts_multiple_iterations(self):
        """Multiple iterations should be valid."""
        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            iterations=[
                BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                BenchmarkIterationInput(iteration_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff"),
                BenchmarkIterationInput(iteration_id="cccccccc-dddd-eeee-ffff-000000000000"),
            ],
        )
        assert len(request.iterations) == 3

    def test_provenance_canonicalizes_dids_to_uuids(self):
        """DIDs in provenance should be canonicalized to UUIDs."""
        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            provenance=["did:web:did.amd.com:11111111-2222-3333-4444-555555555555"],
            iterations=[BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
        )
        assert request.provenance == ["11111111-2222-3333-4444-555555555555"]

    def test_provenance_rejects_duplicates(self):
        """Duplicate provenance items should raise DuplicateProvenanceError."""
        with pytest.raises(DuplicateProvenanceError):
            RecordBenchmarkRequest(
                benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                provenance=[
                    "11111111-2222-3333-4444-555555555555",
                    "11111111-2222-3333-4444-555555555555",
                ],
                iterations=[BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
            )


class TestBenchmarkIterationInputModel:
    """Tests for BenchmarkIterationInput Pydantic model validation."""

    def test_valid_iteration_with_all_fields(self):
        """Iteration with all fields should validate."""
        iteration = BenchmarkIterationInput(
            iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            artefact_metadata={"run": 1, "score": 123.45},
            backlink="https://epdw.example.com/iterations/iter-1",
            provenance=["11111111-2222-3333-4444-555555555555"],
        )

        assert iteration.iteration_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert iteration.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1"
        assert iteration.artefact_metadata == {"run": 1, "score": 123.45}
        assert iteration.backlink == "https://epdw.example.com/iterations/iter-1"
        assert iteration.provenance == ["11111111-2222-3333-4444-555555555555"]

    def test_valid_iteration_minimal(self):
        """Iteration with only iteration_id should validate."""
        iteration = BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")

        assert iteration.iteration_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert iteration.artefact_hash is None
        assert iteration.artefact_metadata is None
        assert iteration.backlink is None
        assert iteration.provenance is None

    def test_iteration_id_validates_uuid(self):
        """Valid UUID should be accepted for iteration_id."""
        iteration = BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
        assert iteration.iteration_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_iteration_id_rejects_invalid_uuid(self):
        """Invalid UUID should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            BenchmarkIterationInput(iteration_id="not-a-valid-uuid")
        assert "iteration_id" in str(exc.value)

    def test_artefact_hash_validates(self):
        """Valid multihash should be accepted on iteration."""
        iteration = BenchmarkIterationInput(
            iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
        )
        assert iteration.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1"


# =============================================================================
# RecordBenchmark Route Logic Tests
# =============================================================================


class TestRecordBenchmarkRoute:
    """Tests for /epdw/record-benchmark endpoint logic."""

    def test_record_benchmark_creates_benchmark_and_iterations(self, did_service_no_migrations, vault_service):
        """Happy path - creates benchmark and iteration artefacts."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import record_benchmark

        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            artefact_metadata={"name": "SPEC CPU 2017"},
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                    artefact_metadata={"run": 1, "score": 123.45},
                )
            ],
        )

        # Call the endpoint function directly
        import asyncio
        response = asyncio.run(record_benchmark(request, api_token="test-token", did_svc=did_service))

        # Verify benchmark was created
        assert response.benchmark_did == "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert response.benchmark_version == 1
        assert response.partial_failure is False

        # Verify iteration was created
        assert len(response.iterations) == 1
        iter_result = response.iterations[0]
        assert iter_result.iteration_id == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert iter_result.iteration_did == "did:web:did.amd.com:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        assert iter_result.version == 1
        assert iter_result.status == "created"
        assert iter_result.error is None

    def test_record_benchmark_sets_iteration_provenance_correctly(self, did_service_no_migrations, vault_service):
        """Benchmark ID should be first in iteration provenance."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import record_benchmark

        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            iterations=[
                BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
            ],
        )

        import asyncio
        asyncio.run(record_benchmark(request, api_token="test-token", did_svc=did_service))

        # Check iteration provenance in database
        iteration = did_service.find_by_external_uid("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "epdw")
        assert iteration is not None
        assert iteration.provenance is not None
        assert iteration.provenance[0] == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

    def test_record_benchmark_duplicate_iteration_ids_raises_400(self, did_service_no_migrations):
        """Duplicate iteration IDs should raise DuplicateIterationIdsError."""
        did_service = did_service_no_migrations

        from app.routers.epdw import record_benchmark

        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            iterations=[
                BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            ],
        )

        import asyncio
        with pytest.raises(DuplicateIterationIdsError) as exc:
            asyncio.run(record_benchmark(request, api_token="test-token", did_svc=did_service))
        assert "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" in str(exc.value)

    def test_record_benchmark_iteration_id_matches_benchmark_id_raises_400(self, did_service_no_migrations):
        """Iteration ID matching benchmark ID should raise IterationIdMatchesBenchmarkIdError."""
        did_service = did_service_no_migrations

        from app.routers.epdw import record_benchmark

        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            iterations=[
                BenchmarkIterationInput(iteration_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c"),
            ],
        )

        import asyncio
        with pytest.raises(IterationIdMatchesBenchmarkIdError) as exc:
            asyncio.run(record_benchmark(request, api_token="test-token", did_svc=did_service))
        assert "95da4dd5-6e48-4c5b-bb91-935983c16d9c" in str(exc.value)

    def test_record_benchmark_invalid_benchmark_provenance_raises_409(self, did_service_no_migrations):
        """Non-existent benchmark provenance should raise ProvenanceNotFoundError."""
        did_service = did_service_no_migrations

        from app.routers.epdw import record_benchmark

        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            provenance=["99999999-9999-9999-9999-999999999999"],
            iterations=[
                BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
            ],
        )

        import asyncio
        with pytest.raises(ProvenanceNotFoundError) as exc:
            asyncio.run(record_benchmark(request, api_token="test-token", did_svc=did_service))
        assert "99999999-9999-9999-9999-999999999999" in str(exc.value)

    def test_record_benchmark_invalid_iteration_provenance_raises_409(self, did_service_no_migrations):
        """Non-existent iteration provenance should raise ProvenanceNotFoundError."""
        did_service = did_service_no_migrations

        from app.routers.epdw import record_benchmark

        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    provenance=["88888888-8888-8888-8888-888888888888"],
                )
            ],
        )

        import asyncio
        with pytest.raises(ProvenanceNotFoundError) as exc:
            asyncio.run(record_benchmark(request, api_token="test-token", did_svc=did_service))
        assert "88888888-8888-8888-8888-888888888888" in str(exc.value)

    def test_record_benchmark_partial_failure_mode(self, did_service_no_migrations, vault_service):
        """Iterations with unchanged data should return status='unchanged' (not an error)."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import record_benchmark

        # First call - create benchmark and first iteration successfully
        request1 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                ),
            ],
        )

        import asyncio
        response1 = asyncio.run(record_benchmark(request1, api_token="test-token", did_svc=did_service))
        assert response1.partial_failure is False

        # Second call - add new iteration + resend existing iteration with same data
        # With idempotent behavior, the existing iteration should return "unchanged" status
        request2 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
            iterations=[
                BenchmarkIterationInput(iteration_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff"),
                # This iteration has same hash as existing - treated as "unchanged"
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                ),
            ],
        )

        response2 = asyncio.run(record_benchmark(request2, api_token="test-token", did_svc=did_service))

        # Benchmark should succeed (updated)
        assert response2.benchmark_version == 2
        assert response2.partial_failure is False  # No actual failures

        # First iteration should succeed (new)
        assert response2.iterations[0].status == "created"
        assert response2.iterations[0].error is None

        # Second iteration should be unchanged (not an error)
        assert response2.iterations[1].status == "unchanged"
        assert response2.iterations[1].version == 1  # Same version
        assert response2.iterations[1].error is None

    def test_record_benchmark_updates_existing_benchmark(self, did_service_no_migrations, vault_service):
        """Calling with existing benchmark_id should create new version."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import record_benchmark

        # Create initial version
        request1 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            iterations=[BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
        )

        import asyncio
        response1 = asyncio.run(record_benchmark(request1, api_token="test-token", did_svc=did_service))
        assert response1.benchmark_version == 1

        # Update with different hash
        request2 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
            iterations=[BenchmarkIterationInput(iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")],
        )

        response2 = asyncio.run(record_benchmark(request2, api_token="test-token", did_svc=did_service))
        assert response2.benchmark_version == 2

    def test_record_benchmark_updates_existing_iteration(self, did_service_no_migrations, vault_service):
        """Calling with existing iteration_id should create new version."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import record_benchmark

        # Create initial version
        request1 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_metadata={"version": 1},
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                )
            ],
        )

        import asyncio
        response1 = asyncio.run(record_benchmark(request1, api_token="test-token", did_svc=did_service))
        assert response1.iterations[0].version == 1
        assert response1.iterations[0].status == "created"

        # Update iteration with different hash (and change benchmark metadata to avoid ArtefactNoChangesError)
        request2 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_metadata={"version": 2},
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                )
            ],
        )

        response2 = asyncio.run(record_benchmark(request2, api_token="test-token", did_svc=did_service))
        assert response2.iterations[0].version == 2
        assert response2.iterations[0].status == "updated"

    def test_record_benchmark_removes_duplicate_benchmark_from_iteration_provenance(self, did_service_no_migrations, vault_service):
        """Benchmark ID should not be duplicated in iteration provenance."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import record_benchmark
        from app.services.did_service import ArtefactInput

        # First create the benchmark so it exists for provenance validation
        first_request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            iterations=[
                BenchmarkIterationInput(iteration_id="00000000-0000-0000-0000-000000000000"),
            ],
        )

        import asyncio
        asyncio.run(record_benchmark(first_request, api_token="test-token", did_svc=did_service))

        # Create a parent artefact for additional provenance
        parent = did_service.upsert_artefact(ArtefactInput(
            external_uid="77777777-7777-7777-7777-777777777777",
            division="epdw",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
        ))

        # Now record a new iteration with both parent and benchmark_id in provenance
        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    provenance=[
                        "77777777-7777-7777-7777-777777777777",
                        "95da4dd5-6e48-4c5b-bb91-935983c16d9c",  # Duplicate of benchmark_id
                    ],
                )
            ],
        )

        asyncio.run(record_benchmark(request, api_token="test-token", did_svc=did_service))

        # Check iteration provenance - benchmark_id should be first and only once
        iteration = did_service.find_by_external_uid("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "epdw")
        assert iteration.provenance == [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "77777777-7777-7777-7777-777777777777",
        ]

    def test_record_benchmark_idempotent_no_changes(self, did_service_no_migrations, vault_service):
        """Calling with exact same data should return unchanged status."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import record_benchmark

        # First call - creates everything
        request = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            artefact_metadata={"name": "SPEC CPU 2017"},
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                )
            ],
        )

        import asyncio
        response1 = asyncio.run(record_benchmark(request, api_token="test-token", did_svc=did_service))
        assert response1.benchmark_status == "created"
        assert response1.benchmark_version == 1
        assert response1.iterations[0].status == "created"

        # Second call - same data should return unchanged
        response2 = asyncio.run(record_benchmark(request, api_token="test-token", did_svc=did_service))
        assert response2.benchmark_status == "unchanged"
        assert response2.benchmark_version == 1  # Same version
        assert response2.iterations[0].status == "unchanged"
        assert response2.iterations[0].version == 1  # Same version
        assert response2.partial_failure is False

    def test_record_benchmark_add_new_iterations_to_existing(self, did_service_no_migrations, vault_service):
        """Adding new iterations to existing benchmark should work."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import record_benchmark

        # First call - create benchmark with 2 iterations
        request1 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                ),
                BenchmarkIterationInput(
                    iteration_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
                ),
            ],
        )

        import asyncio
        response1 = asyncio.run(record_benchmark(request1, api_token="test-token", did_svc=did_service))
        assert response1.benchmark_status == "created"
        assert len(response1.iterations) == 2

        # Second call - add 2 new iterations (keep benchmark same)
        request2 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",  # Same
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="cccccccc-dddd-eeee-ffff-000000000000",  # NEW
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD4",
                ),
                BenchmarkIterationInput(
                    iteration_id="dddddddd-eeee-ffff-0000-111111111111",  # NEW
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD5",
                ),
            ],
        )

        response2 = asyncio.run(record_benchmark(request2, api_token="test-token", did_svc=did_service))
        assert response2.benchmark_status == "unchanged"  # Benchmark same
        assert response2.benchmark_version == 1
        assert len(response2.iterations) == 2
        assert response2.iterations[0].status == "created"  # New iteration
        assert response2.iterations[1].status == "created"  # New iteration
        assert response2.partial_failure is False

    def test_record_benchmark_mix_new_and_existing_iterations(self, did_service_no_migrations, vault_service):
        """Mix of new, unchanged, and updated iterations."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import record_benchmark

        # First call - create benchmark + 2 iterations
        request1 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                ),
                BenchmarkIterationInput(
                    iteration_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
                ),
            ],
        )

        import asyncio
        response1 = asyncio.run(record_benchmark(request1, api_token="test-token", did_svc=did_service))

        # Second call - update benchmark, keep iter-1 same, update iter-2, add iter-3
        request2 = RecordBenchmarkRequest(
            benchmark_id="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD9",  # Changed
            iterations=[
                BenchmarkIterationInput(
                    iteration_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",  # Same
                ),
                BenchmarkIterationInput(
                    iteration_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD8",  # Changed
                ),
                BenchmarkIterationInput(
                    iteration_id="cccccccc-dddd-eeee-ffff-000000000000",  # NEW
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD4",
                ),
            ],
        )

        response2 = asyncio.run(record_benchmark(request2, api_token="test-token", did_svc=did_service))

        assert response2.benchmark_status == "updated"
        assert response2.benchmark_version == 2
        assert len(response2.iterations) == 3

        # Check statuses
        assert response2.iterations[0].status == "unchanged"  # iter-1
        assert response2.iterations[0].version == 1
        assert response2.iterations[1].status == "updated"  # iter-2
        assert response2.iterations[1].version == 2
        assert response2.iterations[2].status == "created"  # iter-3
        assert response2.iterations[2].version == 1
        assert response2.partial_failure is False


# =============================================================================
# UpdateMultipleArtefactsRequest Model Validation Tests
# =============================================================================


class TestUpdateMultipleArtefactsRequestModel:
    """Tests for UpdateMultipleArtefactsRequest Pydantic model validation."""

    def test_valid_request_with_single_update(self):
        """Request with single update should validate."""
        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(
                    external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
                    artefact_metadata={"score": 456.78},
                )
            ]
        )

        assert len(request.updates) == 1
        assert request.updates[0].external_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

    def test_valid_request_with_multiple_updates(self):
        """Request with multiple updates should validate."""
        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c"),
                ArtefactUpdateInput(external_uid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
                ArtefactUpdateInput(external_uid="bbbbbbbb-cccc-dddd-eeee-ffffffffffff"),
            ]
        )

        assert len(request.updates) == 3

    def test_updates_rejects_empty_list(self):
        """Empty updates list should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            UpdateMultipleArtefactsRequest(updates=[])
        assert "updates" in str(exc.value)

    def test_external_uid_validates_uuid(self):
        """Valid UUID should be accepted for external_uid."""
        update = ArtefactUpdateInput(external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c")
        assert update.external_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"

    def test_external_uid_rejects_invalid(self):
        """Invalid UUID should raise ValidationError."""
        with pytest.raises(ValidationError) as exc:
            ArtefactUpdateInput(external_uid="not-a-valid-uuid")
        assert "external_uid" in str(exc.value)

    def test_provenance_canonicalizes_dids(self):
        """DIDs should be canonicalized to UUIDs."""
        update = ArtefactUpdateInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            provenance=["did:web:did.amd.com:11111111-2222-3333-4444-555555555555"],
        )
        assert update.provenance == ["11111111-2222-3333-4444-555555555555"]

    def test_provenance_rejects_duplicates(self):
        """Duplicate provenance should raise DuplicateProvenanceError."""
        with pytest.raises(DuplicateProvenanceError):
            ArtefactUpdateInput(
                external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                provenance=[
                    "11111111-2222-3333-4444-555555555555",
                    "11111111-2222-3333-4444-555555555555",
                ],
            )


class TestArtefactUpdateInputModel:
    """Tests for ArtefactUpdateInput Pydantic model validation."""

    def test_valid_update_with_all_fields(self):
        """Update with all fields should validate."""
        update = ArtefactUpdateInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            artefact_metadata={"score": 456.78, "status": "completed"},
            backlink="https://epdw.example.com/artefacts/art-123",
            provenance=["11111111-2222-3333-4444-555555555555"],
        )

        assert update.external_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert update.artefact_hash == "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"
        assert update.artefact_metadata == {"score": 456.78, "status": "completed"}
        assert update.backlink == "https://epdw.example.com/artefacts/art-123"
        assert update.provenance == ["11111111-2222-3333-4444-555555555555"]

    def test_valid_update_minimal(self):
        """Update with only external_uid should validate."""
        update = ArtefactUpdateInput(external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c")

        assert update.external_uid == "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert update.artefact_hash is None
        assert update.artefact_metadata is None
        assert update.backlink is None
        assert update.provenance is None


# =============================================================================
# UpdateMultipleArtefacts Route Logic Tests
# =============================================================================


class TestUpdateMultipleArtefactsRoute:
    """Tests for /epdw/update-multiple-artefacts endpoint logic."""

    def test_update_multiple_artefacts_success(self, did_service_no_migrations, vault_service):
        """Happy path - all updates succeed."""
        did_service = did_service_no_migrations
        vault_service.ensure_division_signing_key("epdw")

        from app.routers.epdw import update_multiple_artefacts
        from app.services.did_service import ArtefactInput

        # Create existing artefacts
        artefact1 = did_service.upsert_artefact(ArtefactInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            division="epdw",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
        ))

        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(
                    external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                )
            ]
        )

        import asyncio
        response = asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))

        assert response.total == 1
        assert response.successful == 1
        assert response.failed == 0
        assert response.partial_failure is False
        assert response.results[0].status == "updated"
        assert response.results[0].version == 2

    def test_update_multiple_artefacts_duplicate_uids_raises_400(self, did_service_no_migrations):
        """Duplicate external UIDs should raise DuplicateExternalUidsError."""
        did_service = did_service_no_migrations

        from app.routers.epdw import update_multiple_artefacts

        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c"),
                ArtefactUpdateInput(external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c"),
            ]
        )

        import asyncio
        with pytest.raises(DuplicateExternalUidsError) as exc:
            asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))
        assert "95da4dd5-6e48-4c5b-bb91-935983c16d9c" in str(exc.value)

    def test_update_multiple_artefacts_not_found_raises_404(self, did_service_no_migrations):
        """Non-existent artefact should raise ArtefactsNotFoundError."""
        did_service = did_service_no_migrations

        from app.routers.epdw import update_multiple_artefacts

        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(external_uid="99999999-9999-9999-9999-999999999999")
            ]
        )

        import asyncio
        with pytest.raises(ArtefactsNotFoundError) as exc:
            asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))
        assert "99999999-9999-9999-9999-999999999999" in str(exc.value)

    def test_update_multiple_artefacts_wrong_division_raises_404(self, did_service_no_migrations):
        """Artefact in different division should raise ArtefactsNotFoundError."""
        did_service = did_service_no_migrations

        from app.routers.epdw import update_multiple_artefacts
        from app.services.did_service import ArtefactInput

        # Create artefact in advisory division
        artefact = did_service.upsert_artefact(ArtefactInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            division="advisory",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
        ))

        # Try to update it via EPDW endpoint
        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c")
            ]
        )

        import asyncio
        with pytest.raises(ArtefactsNotFoundError):
            asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))

    def test_update_multiple_artefacts_invalid_provenance_raises_409(self, did_service_no_migrations):
        """Non-existent provenance should raise ProvenanceNotFoundError."""
        did_service = did_service_no_migrations

        from app.routers.epdw import update_multiple_artefacts
        from app.services.did_service import ArtefactInput

        # Create existing artefact
        artefact = did_service.upsert_artefact(ArtefactInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            division="epdw",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
        ))

        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(
                    external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                    provenance=["88888888-8888-8888-8888-888888888888"],
                )
            ]
        )

        import asyncio
        with pytest.raises(ProvenanceNotFoundError):
            asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))

    def test_update_multiple_artefacts_no_changes_returns_unchanged(self, did_service_no_migrations):
        """Update with no actual changes should return unchanged status."""
        did_service = did_service_no_migrations

        from app.routers.epdw import update_multiple_artefacts
        from app.services.did_service import ArtefactInput

        # Create existing artefact
        artefact = did_service.upsert_artefact(ArtefactInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            division="epdw",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            artefact_metadata={"score": 123.45},
        ))

        # Update with same data
        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(
                    external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
                    artefact_metadata={"score": 123.45},
                )
            ]
        )

        import asyncio
        response = asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))

        assert response.results[0].status == "unchanged"
        assert response.results[0].version == 1  # Version unchanged

    def test_update_multiple_artefacts_partial_failure_mode(self, did_service_no_migrations):
        """Some updates failing should result in partial_failure=True."""
        did_service = did_service_no_migrations

        from app.routers.epdw import update_multiple_artefacts
        from app.services.did_service import ArtefactInput

        # Create first artefact
        artefact1 = did_service.upsert_artefact(ArtefactInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            division="epdw",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
        ))

        # Second artefact doesn't exist - will fail pre-validation
        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(
                    external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                ),
                ArtefactUpdateInput(
                    external_uid="99999999-9999-9999-9999-999999999999",
                ),
            ]
        )

        import asyncio
        with pytest.raises(ArtefactsNotFoundError):
            # Pre-validation will catch this before processing
            asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))

    def test_update_multiple_artefacts_preserves_artefact_type(self, did_service_no_migrations):
        """Artefact type should be preserved from existing artefact."""
        did_service = did_service_no_migrations

        from app.routers.epdw import update_multiple_artefacts
        from app.services.did_service import ArtefactInput

        # Create artefact with specific type
        artefact = did_service.upsert_artefact(ArtefactInput(
            external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            division="epdw",
            artefact_type="benchmark",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
        ))

        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(
                    external_uid="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                )
            ]
        )

        import asyncio
        response = asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))

        # Check updated artefact still has the type
        updated = did_service.find_by_external_uid("95da4dd5-6e48-4c5b-bb91-935983c16d9c", "epdw")
        assert updated.artefact_type == "benchmark"

    def test_update_multiple_artefacts_preserves_parent_benchmark_in_provenance(self, did_service_no_migrations):
        """Parent benchmark should remain first in iteration provenance."""
        did_service = did_service_no_migrations

        from app.routers.epdw import update_multiple_artefacts
        from app.services.did_service import ArtefactInput

        # Create benchmark
        benchmark = did_service.upsert_artefact(ArtefactInput(
            external_uid="11111111-1111-1111-1111-111111111111",
            division="epdw",
            artefact_type="benchmark",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
        ))

        # Create iteration with benchmark in provenance
        iteration = did_service.upsert_artefact(ArtefactInput(
            external_uid="22222222-2222-2222-2222-222222222222",
            division="epdw",
            artefact_type="benchmark_iteration",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
            provenance=["11111111-1111-1111-1111-111111111111"],
        ))

        # Create another artefact for additional provenance
        other = did_service.upsert_artefact(ArtefactInput(
            external_uid="33333333-3333-3333-3333-333333333333",
            division="epdw",
            artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
        ))

        # Update iteration, adding other provenance
        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(
                    external_uid="22222222-2222-2222-2222-222222222222",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD4",
                    provenance=["33333333-3333-3333-3333-333333333333"],
                )
            ]
        )

        import asyncio
        response = asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))

        # Check provenance - benchmark should still be first
        updated = did_service.find_by_external_uid("22222222-2222-2222-2222-222222222222", "epdw")
        assert updated.provenance[0] == "11111111-1111-1111-1111-111111111111"
        assert "33333333-3333-3333-3333-333333333333" in updated.provenance

    def test_update_multiple_artefacts_response_counts(self, did_service_no_migrations):
        """Response counts should be accurate."""
        did_service = did_service_no_migrations

        from app.routers.epdw import update_multiple_artefacts
        from app.services.did_service import ArtefactInput

        # Create artefacts with valid UUIDs
        artefact_uids = [
            "aaaaaaaa-0000-0000-0000-000000000000",
            "bbbbbbbb-0000-0000-0000-000000000000",
            "cccccccc-0000-0000-0000-000000000000",
        ]

        for uid in artefact_uids:
            did_service.upsert_artefact(ArtefactInput(
                external_uid=uid,
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD1",
            ))

        request = UpdateMultipleArtefactsRequest(
            updates=[
                ArtefactUpdateInput(
                    external_uid="aaaaaaaa-0000-0000-0000-000000000000",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD2",
                ),
                ArtefactUpdateInput(
                    external_uid="bbbbbbbb-0000-0000-0000-000000000000",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD3",
                ),
                ArtefactUpdateInput(
                    external_uid="cccccccc-0000-0000-0000-000000000000",
                    artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGD4",
                ),
            ]
        )

        import asyncio
        response = asyncio.run(update_multiple_artefacts(request, api_token="test-token", did_svc=did_service))

        assert response.total == 3
        assert response.successful == 3
        assert response.failed == 0
        assert response.partial_failure is False
