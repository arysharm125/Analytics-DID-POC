"""DID Router for SUT (System Under Test) DID operations."""

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.routers.basetypes import (
    AMDWebDID,
    ArtefactFieldsMixin,
    PathUUID,
    UUIDString,
    did_from_uuid,
)
from app.routers.dependencies import APITokenDep401Response, DIDServiceDep, EPDWTokenDep
from app.routers.responses import bad_request_response, conflict_response, not_found_response
from app.services.did_service import ArtefactInput, DIDService, artefact_has_changes
from app.services.exceptions import (
    ArtefactNoChangesError,
    ArtefactsNotFoundError,
    DuplicateExternalUidsError,
    DuplicateIterationIdsError,
    IterationIdMatchesBenchmarkIdError,
)

# ==========================
# Constants
# ==========================
_EPDW_DIVISION = "epdw"
_ARTEFACT_TYPE_BENCHMARK = "benchmark"
_ARTEFACT_TYPE_BENCHMARK_ITERATION = "benchmark_iteration"

# Example UUIDs for OpenAPI documentation
_example_benchmark_id = f"{uuid4()}"
_example_iteration_id_1 = f"{uuid4()}"

# ==========================
# Logging
# ==========================
logger = logging.getLogger("did_router")
logger.setLevel(logging.INFO)


# ==========================
# Router
# ==========================
app = APIRouter(tags=["EPDW APIs"], prefix=f"/{_EPDW_DIVISION}")


# ==========================
# API Models
# ==========================
class CreateSutRequest(BaseModel):
    """Request model for creating SUT DIDs."""
    benchmarkExecutionID: UUIDString = Field(  # noqa: N815
        ...,
        description="Unique identifier for the benchmark execution",
        examples=["95da4dd5-6e48-4c5b-bb91-935983c16d9c"]
    )


class IterationDIDInfo(BaseModel):
    """Information about a created iteration DID."""
    iterationID: str  # noqa: N815
    did: str


class CreateSutResponse(BaseModel):
    """Response model for create-sut-did endpoint."""
    status: str = Field(description="'created' or 'exists'")
    benchmarkExecutionID: str  # noqa: N815
    mode: str = Field(description="'single' or 'multi'")
    master_did: str
    iterations: list[IterationDIDInfo]
    vc_status: str = Field(default="separate_endpoint")


class DIDAppendRequest(BaseModel):
    """Request model for appending data to a DID."""
    benchmarkExecutionID: UUIDString = Field(  # noqa: N815
        ...,
        description="Benchmark execution ID",
        examples=["95da4dd5-6e48-4c5b-bb91-935983c16d9c"]
    )
    iterationID: UUIDString = Field(  # noqa: N815
        ...,
        description="Iteration ID to update",
        json_schema_extra={"example": "43f418f6-3808-4e81-bf42-6e8d11def355"},
    )
    data: dict[str, Any] = Field(
        ...,
        description="Data to merge/update. Protected keys like '_id', 'did' are blocked.",
        examples=[{"key": "value", "otherkey": "othervalue"}]
    )


class AppendDIDResponse(BaseModel):
    """Response model for append-did endpoint."""
    status: str
    benchmarkExecutionID: str  # noqa: N815
    iterationID: str  # noqa: N815
    did: str
    previous_did: str | None
    version: int
    diff: dict[str, Any]
    message: str


class BenchmarkIterationInput(ArtefactFieldsMixin):
    """Input for a single benchmark iteration."""
    iteration_id: UUIDString = Field(
        ...,
        description="Unique identifier for this iteration",
        json_schema_extra={"example": _example_iteration_id_1},
        examples=[_example_iteration_id_1],
    )

    # Override artefact_metadata with more specific description/example
    artefact_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata for the iteration",
        json_schema_extra={"example": {"run": 1, "score": 123.45, "runtime_seconds": 342}},
    )

class RecordBenchmarkRequest(ArtefactFieldsMixin):
    """Request model for recording benchmark with iterations."""
    benchmark_id: UUIDString = Field(
        ...,
        description="Unique identifier for the benchmark execution",
        json_schema_extra={"example": _example_benchmark_id},
        examples=[_example_benchmark_id],
    )
    iterations: list[BenchmarkIterationInput] = Field(
        ...,
        description="List of iterations for this benchmark (at least 1 required)"
    )

    # Override artefact_metadata with more specific description/example
    artefact_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata for the benchmark",
        json_schema_extra={"example": {"name": "SPEC CPU 2017", "config": "base", "system": "EPYC 9004"}},
    )

    @field_validator('iterations')
    @classmethod
    def validate_iterations_not_empty(cls, v: list[BenchmarkIterationInput]) -> list[BenchmarkIterationInput]:
        """Ensure at least one iteration is provided."""
        if not v:
            raise ValueError("At least one iteration is required")
        return v


class IterationDIDResult(BaseModel):
    """Result for a single iteration DID."""
    iteration_id: str
    iteration_did: AMDWebDID = Field(
        description="DID for the iteration (based on iteration_id)"
    )
    version_did: AMDWebDID = Field(
        description="DID for the specific version created"
    )
    version: int
    status: str = Field(
        description="Status: 'created', 'updated', or 'error'"
    )
    error: str | None = Field(
        default=None,
        description="Error message if status is 'error'"
    )


class RecordBenchmarkResponse(BaseModel):
    """Response model for record-benchmark endpoint."""
    benchmark_did: AMDWebDID = Field(
        description="DID for the benchmark (based on benchmark_id)"
    )
    benchmark_version_did: AMDWebDID = Field(
        description="DID for the specific benchmark version created"
    )
    benchmark_version: int
    benchmark_status: str = Field(
        description="Status: 'created', 'updated', or 'unchanged'"
    )
    iterations: list[IterationDIDResult]
    partial_failure: bool = Field(
        description="True if any iteration failed to be created"
    )


class ArtefactUpdateInput(ArtefactFieldsMixin):
    """Input for a single artefact update."""
    external_uid: UUIDString = Field(
        ...,
        description="UUID of the existing artefact",
        json_schema_extra={"example": "95da4dd5-6e48-4c5b-bb91-935983c16d9c"},
    )

    # Override artefact_metadata with more specific description/example
    artefact_metadata: dict[str, Any] | None = Field(
        default=None,
        description="Full metadata to set for this version",
        json_schema_extra={"example": {"score": 456.78, "status": "completed"}},
    )

    # Override backlink with more specific example
    backlink: str | None = Field(
        default=None,
        description="Optional URL back to the artefact in the originating system",
        json_schema_extra={"example": "https://epdw.example.com/artefacts/art-123"},
    )

    # Override update_message with more specific example
    update_message: str | None = Field(
        default=None,
        description="Optional message describing this update",
        json_schema_extra={"example": "Updated metadata"},
    )


class UpdateMultipleArtefactsRequest(BaseModel):
    """Request model for updating multiple artefacts."""
    updates: list[ArtefactUpdateInput] = Field(
        ...,
        description="List of artefact updates (at least 1 required)",
        min_length=1,
    )


class ArtefactUpdateResult(BaseModel):
    """Result for a single artefact update."""
    external_uid: str
    artefact_did: AMDWebDID
    version_did: AMDWebDID
    version: int
    previous_version: int | None
    status: str = Field(description="Status: 'created', 'updated', 'unchanged', or 'error'")
    error: str | None = Field(
        default=None,
        description="Error message if status is 'error'"
    )


class UpdateMultipleArtefactsResponse(BaseModel):
    """Response model for update-multiple-artefacts endpoint."""
    results: list[ArtefactUpdateResult]
    partial_failure: bool = Field(
        description="True if any update failed"
    )
    total: int
    successful: int
    failed: int


# ==========================
# Endpoints
# ==========================

@app.get("/did.json")
async def epdw_did(did_svc: DIDServiceDep):
    """Return the DID document that corresponds to the EPDW division.

    This DID document contains the keys that are used to verify digital artefacts
    associated with the EPDW division.

    Returns:
        JSON-LD DID Document.
    """
    return did_svc.division_did_doc(_EPDW_DIVISION)


@app.get("/{uid}/vc.json", responses={**APITokenDep401Response, **not_found_response()})
async def artefact_vc(
    uid: PathUUID,
    api_token: EPDWTokenDep,
    did_svc: DIDServiceDep,
):
    """Return a Verifiable Credential with proofs for a Digital Artefact."""
    return did_svc.issue_artefact_vc(division=_EPDW_DIVISION, uid=uid)


@app.post("/record-benchmark", responses={**APITokenDep401Response, **bad_request_response(), **conflict_response(_EPDW_DIVISION)})
async def record_benchmark(
    request: RecordBenchmarkRequest,
    api_token: EPDWTokenDep,
    did_svc: DIDServiceDep,
) -> RecordBenchmarkResponse:
    """
    Record a benchmark execution with its iterations as DIDs.

    This endpoint creates Digital Artefacts for both the benchmark and its iterations,
    establishing parent-child relationships via provenance.

    **Idempotent Behavior:**
    - Benchmark: If exists with same data → status="unchanged" (no new version)
    - Benchmark: If exists with changed data → status="updated" (new version created)
    - Benchmark: If new → status="created" (version 1)
    - Iterations: Same logic applies (created/updated/unchanged)
    - This allows adding new iterations to existing benchmarks by calling with new iteration IDs

    **Pre-validation Phase:**
    - Validates iteration list is non-empty
    - Checks for duplicate iteration IDs
    - Validates benchmark and iterations, if they exist, they belong to EPDW division
    - Validates all provenance items exist in did_artefacts

    **Processing:**
    1. Checks if benchmark exists and creates/updates/reuses accordingly
    2. Creates/updates iteration artefacts (with partial-success mode)

    **Partial Success:**
    If the benchmark succeeds but some iterations fail, the endpoint returns 200
    with `partial_failure=True` and error details in the iteration results.

    Args:
        request: Benchmark and iteration data
        api_token: EPDW API token (injected)
        did_svc: DID service (injected)

    Returns:
        RecordBenchmarkResponse with DIDs, version info, and status indicators

    Raises:
        400: Empty iterations list or duplicate iteration IDs
        409: Provenance not found, division mismatch, or version conflict
    """
    # PRE-VALIDATION: Check for duplicate iteration IDs
    iteration_ids = [it.iteration_id for it in request.iterations]
    seen_ids = set()
    duplicates = []
    for iter_id in iteration_ids:
        if iter_id in seen_ids:
            duplicates.append(iter_id)
        seen_ids.add(iter_id)

    if duplicates:
        raise DuplicateIterationIdsError(duplicates)

    # PRE-VALIDATION: Check that no iteration ID matches benchmark ID
    matching_benchmark_ids = []
    for iter_id in iteration_ids:
        if iter_id == request.benchmark_id:
            matching_benchmark_ids.append(iter_id)

    if matching_benchmark_ids:
        raise IterationIdMatchesBenchmarkIdError(matching_benchmark_ids)

    # PRE-VALIDATION: Check that iterations and benchmarks, if they exist,
    # they exist in EPDW division.
    all_ids = [*iteration_ids, request.benchmark_id]
    did_svc.validate_ids_may_exist_division(all_ids, _EPDW_DIVISION)

    # PRE-VALIDATION: Validate all provenance items exist
    # Collect all provenance UIDs (benchmark + all iterations)
    collection = did_svc.db.get_collection(DIDService._artefacts_col_name)

    # Validate benchmark provenance if present
    if request.provenance:
        did_svc._validate_id_list_exists(request.provenance, collection)

    # Validate each iteration's provenance if present
    for iteration in request.iterations:
        if iteration.provenance:
            did_svc._validate_id_list_exists(iteration.provenance, collection)

    # CREATE OR UPDATE BENCHMARK ARTEFACT (with idempotent behavior)
    # Check if benchmark already exists
    existing_benchmark = did_svc.find_by_external_uid(request.benchmark_id, _EPDW_DIVISION)

    if existing_benchmark is not None:
        # Benchmark exists - check if data has changed
        has_changes = artefact_has_changes(
            existing=existing_benchmark.model_dump(),
            new_hash=request.artefact_hash,
            new_metadata=request.artefact_metadata,
            new_provenance=list(request.provenance) if request.provenance else None,
            new_artefact_type=_ARTEFACT_TYPE_BENCHMARK,
        )

        if has_changes:
            # Data changed - create new version
            benchmark_record = did_svc.upsert_artefact(ArtefactInput(
                external_uid=request.benchmark_id,
                division=_EPDW_DIVISION,
                artefact_hash=request.artefact_hash,
                artefact_metadata=request.artefact_metadata,
                artefact_type=_ARTEFACT_TYPE_BENCHMARK,
                backlink=request.backlink,
                provenance=request.provenance,
                update_message=request.update_message,
                updated_by=request.updated_by,
            ))
            benchmark_status = "updated"
        else:
            # No changes - reuse existing
            benchmark_record = existing_benchmark
            benchmark_status = "unchanged"
    else:
        # Benchmark doesn't exist - create new
        benchmark_record = did_svc.upsert_artefact(ArtefactInput(
            external_uid=request.benchmark_id,
            division=_EPDW_DIVISION,
            artefact_hash=request.artefact_hash,
            artefact_metadata=request.artefact_metadata,
            artefact_type=_ARTEFACT_TYPE_BENCHMARK,
            backlink=request.backlink,
            provenance=request.provenance,
            update_message=request.update_message,
            updated_by=request.updated_by,
        ))
        benchmark_status = "created"

    benchmark_did = did_from_uuid(benchmark_record.external_uid)
    benchmark_version_did = did_from_uuid(benchmark_record.version_uid)

    logger.info(
        f"Recorded benchmark: id={request.benchmark_id}, "
        f"version={benchmark_record.version}, status={benchmark_status}, did={benchmark_did}"
    )

    # CREATE ITERATION ARTEFACTS (partial-success mode)
    iteration_results: list[IterationDIDResult] = []
    partial_failure = False

    for iteration in request.iterations:
        try:
            # Build provenance: parent benchmark first, then additional items (no duplicates)
            iteration_provenance = list(iteration.provenance) if iteration.provenance else []
            # Remove benchmark_id if already present (to avoid duplicates and ensure correct position)
            if request.benchmark_id in iteration_provenance:
                iteration_provenance.remove(request.benchmark_id)
            # Insert at position 0
            iteration_provenance.insert(0, request.benchmark_id)

            # Upsert iteration artefact
            iteration_record = did_svc.upsert_artefact(ArtefactInput(
                external_uid=iteration.iteration_id,
                division=_EPDW_DIVISION,
                artefact_hash=iteration.artefact_hash,
                artefact_metadata=iteration.artefact_metadata,
                artefact_type=_ARTEFACT_TYPE_BENCHMARK_ITERATION,
                backlink=iteration.backlink,
                provenance=iteration_provenance,
                update_message=iteration.update_message,
                updated_by=iteration.updated_by,
            ))

            # Determine status
            status = "created" if iteration_record.version == 1 else "updated"

            iteration_results.append(IterationDIDResult(
                iteration_id=iteration.iteration_id,
                iteration_did=did_from_uuid(iteration_record.external_uid),
                version_did=did_from_uuid(iteration_record.version_uid),
                version=iteration_record.version,
                status=status,
                error=None,
            ))

            logger.info(
                f"Recorded iteration: id={iteration.iteration_id}, "
                f"version={iteration_record.version}, status={status}"
            )

        except ArtefactNoChangesError:
            # Iteration exists with same data - treat as unchanged (not an error)
            existing_iter = did_svc.find_by_external_uid(iteration.iteration_id, _EPDW_DIVISION)

            # ArtefactNoChangesError means the iteration must exist
            assert existing_iter is not None, "Iteration must exist if ArtefactNoChangesError was raised"

            iteration_results.append(IterationDIDResult(
                iteration_id=iteration.iteration_id,
                iteration_did=did_from_uuid(existing_iter.external_uid),
                version_did=did_from_uuid(existing_iter.version_uid),
                version=existing_iter.version,
                status="unchanged",
                error=None,
            ))

            logger.info(
                f"Iteration unchanged: id={iteration.iteration_id}, "
                f"version={existing_iter.version}"
            )

        except Exception as e:
            # Record the error and continue with next iteration
            partial_failure = True
            error_msg = str(e)

            iteration_results.append(IterationDIDResult(
                iteration_id=iteration.iteration_id,
                iteration_did=did_from_uuid(iteration.iteration_id),
                version_did=did_from_uuid(iteration.iteration_id),
                version=0,
                status="error",
                error=error_msg,
            ))

            logger.error(
                f"Failed to record iteration: id={iteration.iteration_id}, "
                f"error={error_msg}"
            )

    # Return response
    return RecordBenchmarkResponse(
        benchmark_did=benchmark_did,
        benchmark_version_did=benchmark_version_did,
        benchmark_version=benchmark_record.version,
        benchmark_status=benchmark_status,
        iterations=iteration_results,
        partial_failure=partial_failure,
    )


@app.post("/update-multiple-artefacts", responses={**APITokenDep401Response, **bad_request_response(), **not_found_response("Resource"), **conflict_response(_EPDW_DIVISION)})
async def update_multiple_artefacts(
    request: UpdateMultipleArtefactsRequest,
    api_token: EPDWTokenDep,
    did_svc: DIDServiceDep,
) -> UpdateMultipleArtefactsResponse:
    """
    Update multiple existing artefacts with new data.

    This endpoint updates existing Digital Artefacts by creating new versions
    with the provided data.

    **Pre-validation Phase:**
    - Validates update list is non-empty
    - Checks for duplicate artefact UIDs
    - Verifies all artefacts exist in the EPDW division
    - Validates all provenance items exist in did_artefacts

    **Processing:**
    Creates new versions for each artefact (with partial-success mode)

    **Partial Success:**
    If pre-validation passes but some updates fail during processing, the endpoint
    returns 200 with `partial_failure=True` and error details in the results.

    Args:
        request: List of artefact updates
        api_token: EPDW API token (injected)
        did_svc: DID service (injected)

    Returns:
        UpdateMultipleArtefactsResponse with update results

    Raises:
        400: Empty updates list or duplicate artefact UIDs
        404: One or more artefacts not found in division
        409: Provenance not found, division mismatch, or version conflict
    """
    # PRE-VALIDATION: Check for duplicate external UIDs
    external_uids = [update.external_uid for update in request.updates]
    seen_uids = set()
    duplicates = []
    for uid in external_uids:
        if uid in seen_uids:
            duplicates.append(uid)
        seen_uids.add(uid)

    if duplicates:
        raise DuplicateExternalUidsError(duplicates)

    # PRE-VALIDATION: Verify all artefacts exist in EPDW division
    existing_artefacts = {}  # uid → ArtefactRecord (cached for later use)
    missing = []
    for update in request.updates:
        artefact = did_svc.find_by_external_uid(update.external_uid, _EPDW_DIVISION)
        if artefact is None:
            missing.append(update.external_uid)
        else:
            existing_artefacts[update.external_uid] = artefact

    if missing:
        raise ArtefactsNotFoundError(missing, _EPDW_DIVISION)

    # PRE-VALIDATION: Collect and validate all provenance UIDs
    collection = did_svc.db.get_collection(DIDService._artefacts_col_name)
    all_provenance_uids = set()
    for update in request.updates:
        if update.provenance:
            all_provenance_uids.update(update.provenance)

    # Validate each unique provenance item exists
    for prov_uid in all_provenance_uids:
        did_svc._validate_id_list_exists([prov_uid], collection)

    # PROCESS UPDATES (partial-success mode)
    results: list[ArtefactUpdateResult] = []
    successful_count = 0
    failed_count = 0

    for update in request.updates:
        try:
            # Get the existing artefact to preserve artefact_type
            existing = existing_artefacts[update.external_uid]

            # Prepare final provenance
            final_provenance = list(update.provenance) if update.provenance else []

            # For benchmark_iteration, ensure parent benchmark UID is FIRST in provenance
            if existing.artefact_type == _ARTEFACT_TYPE_BENCHMARK_ITERATION:
                existing_prov = list(existing.provenance) if existing.provenance else []
                if existing_prov:
                    # First item in existing provenance is the parent benchmark
                    parent_benchmark_uid = existing_prov[0]
                    # Remove from current position if present (to avoid duplicates and ensure correct position)
                    if parent_benchmark_uid in final_provenance:
                        final_provenance.remove(parent_benchmark_uid)
                    # Always insert at position 0
                    final_provenance.insert(0, parent_benchmark_uid)

            # CHECK FOR CHANGES: Use artefact_has_changes to detect if update is needed
            # Convert ArtefactRecord to dict for comparison
            existing_dict = existing.model_dump()
            has_changes = artefact_has_changes(
                existing=existing_dict,
                new_hash=update.artefact_hash,
                new_metadata=update.artefact_metadata,
                new_provenance=final_provenance if final_provenance else None,
                new_artefact_type=existing.artefact_type,  # Type is preserved, so compare against existing
            )

            if not has_changes:
                # No changes detected - skip upsert and report as unchanged
                results.append(ArtefactUpdateResult(
                    external_uid=update.external_uid,
                    artefact_did=did_from_uuid(existing.external_uid),
                    version_did=did_from_uuid(existing.version_uid),
                    version=existing.version,
                    previous_version=None,
                    status="unchanged",
                    error=None,
                ))

                logger.info(
                    f"Skipped artefact (no changes): uid={update.external_uid}, "
                    f"version={existing.version}"
                )
                continue

            # Upsert with new data, preserving artefact_type
            updated_record = did_svc.upsert_artefact(ArtefactInput(
                external_uid=update.external_uid,
                division=_EPDW_DIVISION,
                artefact_hash=update.artefact_hash,
                artefact_metadata=update.artefact_metadata,
                artefact_type=existing.artefact_type,  # Preserve existing type
                backlink=update.backlink,
                provenance=final_provenance if final_provenance else None,
                update_message=update.update_message,
                updated_by=update.updated_by,
            ))

            # Determine status
            status = "created" if updated_record.version == 1 else "updated"
            previous_version = updated_record.version - 1 if updated_record.version > 1 else None

            results.append(ArtefactUpdateResult(
                external_uid=update.external_uid,
                artefact_did=did_from_uuid(updated_record.external_uid),
                version_did=did_from_uuid(updated_record.version_uid),
                version=updated_record.version,
                previous_version=previous_version,
                status=status,
                error=None,
            ))

            successful_count += 1

            logger.info(
                f"Updated artefact: uid={update.external_uid}, "
                f"version={updated_record.version}, status={status}"
            )

        except Exception as e:
            # Record the error and continue with next update
            failed_count += 1
            error_msg = str(e)

            results.append(ArtefactUpdateResult(
                external_uid=update.external_uid,
                artefact_did=did_from_uuid(update.external_uid),
                version_did=did_from_uuid(update.external_uid),
                version=0,
                previous_version=None,
                status="error",
                error=error_msg,
            ))

            logger.error(
                f"Failed to update artefact: uid={update.external_uid}, "
                f"error={error_msg}"
            )

    # Return response
    return UpdateMultipleArtefactsResponse(
        results=results,
        partial_failure=failed_count > 0,
        total=len(request.updates),
        successful=successful_count,
        failed=failed_count,
    )
