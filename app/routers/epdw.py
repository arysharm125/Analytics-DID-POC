"""DID Router for SUT (System Under Test) DID operations."""

import logging
from typing import Annotated, Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.routers.basetypes import AMDWebDID, CanonicalizedUUID, DIDOrUUIDList, Multihash, UUIDString, did_from_uuid
from app.routers.dependencies import EPDWTokenDep, APITokenDep401Response, DIDServiceDep
from app.services.did_service import ArtefactInput
from app.services.exceptions import DuplicateIterationIdsError, ProvenanceNotFoundError
from app.services.sut_service import SUTServiceDep


# ==========================
# Constants
# ==========================
_EPDW_DIVISION = "epdw"

# Example UUIDs for OpenAPI documentation
_example_benchmark_id = f"{uuid4()}"
_example_iteration_id_1 = f"{uuid4()}"
_example_iteration_id_2 = f"{uuid4()}"

# ==========================
# Logging
# ==========================
logger = logging.getLogger("did_router")
logger.setLevel(logging.INFO)


# ==========================
# Router
# ==========================
app = APIRouter(tags=["EPDW APIs"])


async def startup_did_router():
    """
    Startup hook for the DID router.

    Note: Most initialization is now handled by DIDService migrations.
    This function is kept for backward compatibility with main.py.
    """
    logger.info("DID router startup - initialization handled by DIDService")


# ==========================
# API Models
# ==========================
class CreateSutRequest(BaseModel):
    """Request model for creating SUT DIDs."""
    benchmarkExecutionID: UUIDString = Field(
        ...,
        description="Unique identifier for the benchmark execution",
        examples=["95da4dd5-6e48-4c5b-bb91-935983c16d9c"]
    )


class IterationDIDInfo(BaseModel):
    """Information about a created iteration DID."""
    iterationID: str
    did: str


class CreateSutResponse(BaseModel):
    """Response model for create-sut-did endpoint."""
    status: str = Field(description="'created' or 'exists'")
    benchmarkExecutionID: str
    mode: str = Field(description="'single' or 'multi'")
    master_did: str
    iterations: List[IterationDIDInfo]
    vc_status: str = Field(default="separate_endpoint")


class DIDAppendRequest(BaseModel):
    """Request model for appending data to a DID."""
    benchmarkExecutionID: UUIDString = Field(
        ...,
        description="Benchmark execution ID",
        examples=["95da4dd5-6e48-4c5b-bb91-935983c16d9c"]
    )
    iterationID: UUIDString = Field(
        ...,
        description="Iteration ID to update",
        json_schema_extra={"example": "43f418f6-3808-4e81-bf42-6e8d11def355"},
    )
    data: Dict[str, Any] = Field(
        ...,
        description="Data to merge/update. Protected keys like '_id', 'did' are blocked.",
        examples=[{"key": "value", "otherkey": "othervalue"}]
    )


class AppendDIDResponse(BaseModel):
    """Response model for append-did endpoint."""
    status: str
    benchmarkExecutionID: str
    iterationID: str
    did: str
    previous_did: Optional[str]
    version: int
    diff: Dict[str, Any]
    message: str


class BenchmarkIterationInput(BaseModel):
    """Input for a single benchmark iteration."""
    iteration_id: UUIDString = Field(
        ...,
        description="Unique identifier for this iteration",
        json_schema_extra={"example": _example_iteration_id_1},
        examples=[_example_iteration_id_1],
    )
    artefact_hash: Optional[Multihash] = Field(
        default=None,
        description="Optional multihash of iteration data",
        json_schema_extra={"example": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"},
    )
    artefact_metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional metadata for the iteration",
        json_schema_extra={"example": {"run": 1, "score": 123.45, "runtime_seconds": 342}},
    )
    backlink: Optional[str] = Field(
        default=None,
        description="Optional URL back to the iteration in the originating system",
        json_schema_extra={"example": "https://epdw.example.com/iterations/iter-1"},
    )
    provenance: Optional[DIDOrUUIDList] = Field(
        default=None,
        description="Optional additional provenance identifiers (beyond the benchmark itself)",
        json_schema_extra={"example": []},
    )


class RecordBenchmarkRequest(BaseModel):
    """Request model for recording benchmark with iterations."""
    benchmark_id: UUIDString = Field(
        ...,
        description="Unique identifier for the benchmark execution",
        json_schema_extra={"example": _example_benchmark_id},
        examples=[_example_benchmark_id],
    )
    artefact_hash: Optional[Multihash] = Field(
        default=None,
        description="Optional multihash of benchmark data",
        json_schema_extra={"example": "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"},
    )
    artefact_metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional metadata for the benchmark",
        json_schema_extra={"example": {"name": "SPEC CPU 2017", "config": "base", "system": "EPYC 9004"}},
    )
    backlink: Optional[str] = Field(
        default=None,
        description="Optional URL back to the benchmark in the originating system",
        json_schema_extra={"example": "https://epdw.example.com/benchmarks/bench-123"},
    )
    provenance: Optional[DIDOrUUIDList] = Field(
        default=None,
        description="Optional list of provenance identifiers for the benchmark itself",
        json_schema_extra={"example": []},
    )
    iterations: List[BenchmarkIterationInput] = Field(
        ...,
        description="List of iterations for this benchmark (at least 1 required)"
    )

    @field_validator('iterations')
    @classmethod
    def validate_iterations_not_empty(cls, v: List[BenchmarkIterationInput]) -> List[BenchmarkIterationInput]:
        """Ensure at least one iteration is provided."""
        if not v:
            raise ValueError("At least one iteration is required")
        return v


class IterationDIDResult(BaseModel):
    """Result for a single iteration DID."""
    iteration_id: str
    artefact_did: AMDWebDID = Field(
        description="DID for the iteration (based on iteration_id)"
    )
    version_did: AMDWebDID = Field(
        description="DID for the specific version created"
    )
    version: int
    status: str = Field(
        description="Status: 'created', 'updated', or 'error'"
    )
    error: Optional[str] = Field(
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
    iterations: List[IterationDIDResult]
    partial_failure: bool = Field(
        description="True if any iteration failed to be created"
    )


# ==========================
# Conflict Response Documentation
# ==========================
ConflictResponses = {
    409: {
        "description": "Conflict error: Division mismatch or version conflict",
        "content": {
            "application/json": {
                "examples": {
                    "division_mismatch": {
                        "summary": "Division mismatch",
                        "value": {"detail": "Division mismatch: existing division is 'epdw', but attempted to set 'other'"}
                    },
                    "version_conflict": {
                        "summary": "Version conflict",
                        "value": {"detail": "Version conflict: version 2 already exists"}
                    },
                    "provenance_not_found": {
                        "summary": "Provenance item not found",
                        "value": {"detail": "Provenance item not found: 2cacad4f-63ab-4668-9db7-7fc2538caa8c"}
                    }
                }
            }
        }
    }
}

NotFoundResponses = {
    404: {
        "description": "Resource not found",
        "content": {
            "application/json": {
                "examples": {
                    "benchmark_not_found": {
                        "summary": "Benchmark not found",
                        "value": {"detail": "Benchmark 'abc-123' not found"}
                    },
                    "iteration_not_found": {
                        "summary": "Iteration not found",
                        "value": {"detail": "Iteration 'iter-1' not found under benchmark 'abc-123'"}
                    }
                }
            }
        }
    }
}


# ==========================
# Endpoints
# ==========================
@app.post("/create-sut-did", responses={**APITokenDep401Response, **NotFoundResponses, **ConflictResponses})
def create_sut_did(
    req: CreateSutRequest,
    api_token: EPDWTokenDep,
    sut_svc: SUTServiceDep,
):
    """
    Create DIDs for a benchmark execution and its iterations.

    This endpoint creates:
    - A master DID for the benchmark execution
    - Child DIDs for each iteration (linked via provenance)

    The operation is idempotent - if DIDs already exist for the benchmark,
    the existing DIDs are returned.
    """
    result = sut_svc.create_sut_dids(req.benchmarkExecutionID)

    logger.info(
        f"SUT DIDs: benchmark={result.benchmark_id}, "
        f"master_did={result.master_did}, iterations={len(result.iterations)}, "
        f"status={result.status}"
    )

    return JSONResponse({
        "status": result.status,
        "message": result.message,
        "benchmarkExecutionID": result.benchmark_id,
        "mode": result.mode,
        "master_did": result.master_did,
        "iterations": [
            {"iterationID": it.iteration_id, "did": it.did}
            for it in result.iterations
        ],
    })


@app.post("/append-did", responses={**APITokenDep401Response, **NotFoundResponses, **ConflictResponses})
async def append_did(
    body: DIDAppendRequest,
    api_token: EPDWTokenDep,
    sut_svc: SUTServiceDep,
    update_message: str = Query(
        ...,
        description="Message describing the update",
        openapi_examples={"normal":{"value":"Adding new metadata"}},
    ),
    updated_by: str = Query(
        ...,
        description="AMD email of the updater",
        openapi_examples={"normal":{"value":"user@amd.com"}},
    ),
):
    """
    Append/update data to an existing iteration DID.

    Creates a new version of the artefact with the updated metadata.
    The diff between old and new data is computed and returned.
    """
    result = sut_svc.append_to_iteration(
        benchmark_id=body.benchmarkExecutionID,
        iteration_id=body.iterationID,
        data=body.data or {},
        update_message=update_message,
        updated_by=updated_by,
    )


    logger.info(
        f"Updated SUT DID: iteration={result.iteration_id}, "
        f"version={result.version}, updated_by={updated_by}"
    )

    return {
        "status": result.status,
        "benchmarkExecutionID": result.benchmark_id,
        "iterationID": result.iteration_id,
        "did": result.did,
        "previous_did": result.previous_did,
        "version": result.version,
        "diff": result.diff,
        "message": result.message,
    }


@app.get("/epdw/did.json")
async def epdw_DID(did_svc: DIDServiceDep):
    """Return the DID document that corresponds to the EPDW division.

    This DID document contains the keys that are used to verify digital artefacts
    associated with the EPDW division.

    Returns:
        JSON-LD DID Document.
    """
    return did_svc.division_did_doc(_EPDW_DIVISION)

PathUUID = Annotated[CanonicalizedUUID, Path(
    description="The UID or DID of the artefact to retrieve the Verifiable Credential for",
    openapi_examples={"normal":{"value":"95da4dd5-6e48-4c5b-bb91-935983c16d9c"}},
)]

@app.get("/epdw/{uid}/vc.json", responses={**APITokenDep401Response})
async def artefact_vc(
    uid: PathUUID,
    api_token: EPDWTokenDep,
    did_svc: DIDServiceDep,
):
    """Return a Verifiable Credential with proofs for a Digital Artefact."""
    return did_svc.issue_artefact_vc(division=_EPDW_DIVISION, uid=uid)


BadRequestResponses = {
    400: {
        "description": "Bad Request: Invalid input",
        "content": {
            "application/json": {
                "examples": {
                    "duplicate_iteration_ids": {
                        "summary": "Duplicate iteration IDs",
                        "value": {"detail": "Duplicate iteration IDs found: iter-1, iter-2"}
                    },
                    "empty_iterations": {
                        "summary": "Empty iterations list",
                        "value": {"detail": "At least one iteration is required"}
                    }
                }
            }
        }
    }
}


@app.post("/record-benchmark", responses={**APITokenDep401Response, **BadRequestResponses, **ConflictResponses})
async def record_benchmark(
    request: RecordBenchmarkRequest,
    api_token: EPDWTokenDep,
    did_svc: DIDServiceDep,
) -> RecordBenchmarkResponse:
    """
    Record a benchmark execution with its iterations as DIDs.

    This endpoint creates Digital Artefacts for both the benchmark and its iterations,
    establishing parent-child relationships via provenance. Unlike `/create-sut-did`,
    this endpoint receives data directly in the request payload, enabling decoupled
    operation without requiring access to EPDW's internal database.

    **Pre-validation Phase:**
    - Validates iteration list is non-empty
    - Checks for duplicate iteration IDs
    - Validates all provenance items exist in did_artefacts

    **Processing:**
    1. Creates benchmark artefact
    2. Creates iteration artefacts (with partial-success mode)

    **Partial Success:**
    If the benchmark succeeds but some iterations fail, the endpoint returns 200
    with `partial_failure=True` and error details in the iteration results.

    Args:
        request: Benchmark and iteration data
        api_token: EPDW API token (injected)
        did_svc: DID service (injected)

    Returns:
        RecordBenchmarkResponse with DIDs and version info

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

    # PRE-VALIDATION: Validate all provenance items exist
    # Collect all provenance UIDs (benchmark + all iterations)
    collection = did_svc.db.get_collection(did_svc._artefacts_col_name)

    # Validate benchmark provenance if present
    if request.provenance:
        did_svc._validate_id_list_exists(request.provenance, collection)

    # Validate each iteration's provenance if present
    for iteration in request.iterations:
        if iteration.provenance:
            did_svc._validate_id_list_exists(iteration.provenance, collection)

    # CREATE BENCHMARK ARTEFACT
    benchmark_record = did_svc.upsert_artefact(ArtefactInput(
        external_uid=request.benchmark_id,
        division=_EPDW_DIVISION,
        artefact_hash=request.artefact_hash,
        artefact_metadata=request.artefact_metadata,
        artefact_type="benchmark",
        backlink=request.backlink,
        provenance=request.provenance,
    ))

    benchmark_did = did_from_uuid(benchmark_record.external_uid)
    benchmark_version_did = did_from_uuid(benchmark_record.version_uid)

    logger.info(
        f"Recorded benchmark: id={request.benchmark_id}, "
        f"version={benchmark_record.version}, did={benchmark_did}"
    )

    # CREATE ITERATION ARTEFACTS (partial-success mode)
    iteration_results: List[IterationDIDResult] = []
    partial_failure = False

    for iteration in request.iterations:
        try:
            # Build provenance: [benchmark_id] + optional additional provenance
            iteration_provenance = [request.benchmark_id]
            if iteration.provenance:
                iteration_provenance.extend(iteration.provenance)

            # Upsert iteration artefact
            iteration_record = did_svc.upsert_artefact(ArtefactInput(
                external_uid=iteration.iteration_id,
                division=_EPDW_DIVISION,
                artefact_hash=iteration.artefact_hash,
                artefact_metadata=iteration.artefact_metadata,
                artefact_type="benchmark_iteration",
                backlink=iteration.backlink,
                provenance=iteration_provenance,
            ))

            # Determine status
            status = "created" if iteration_record.version == 1 else "updated"

            iteration_results.append(IterationDIDResult(
                iteration_id=iteration.iteration_id,
                artefact_did=did_from_uuid(iteration_record.external_uid),
                version_did=did_from_uuid(iteration_record.version_uid),
                version=iteration_record.version,
                status=status,
                error=None,
            ))

            logger.info(
                f"Recorded iteration: id={iteration.iteration_id}, "
                f"version={iteration_record.version}, status={status}"
            )

        except Exception as e:
            # Record the error and continue with next iteration
            partial_failure = True
            error_msg = str(e)

            iteration_results.append(IterationDIDResult(
                iteration_id=iteration.iteration_id,
                artefact_did=did_from_uuid(iteration.iteration_id),
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
        iterations=iteration_results,
        partial_failure=partial_failure,
    )
