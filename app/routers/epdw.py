"""DID Router for SUT (System Under Test) DID operations."""

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.routers.basetypes import CanonicalizedUUID, UUIDString
from app.routers.dependencies import EPDWTokenDep, APITokenDep401Response, DIDServiceDep
from app.services.sut_service import SUTServiceDep


# ==========================
# Constants
# ==========================
_EPDW_DIVISION = "epdw"

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
    return did_svc.artefact_vc(division=_EPDW_DIVISION, uid=uid)
