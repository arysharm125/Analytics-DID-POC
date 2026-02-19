"""DID Router for SUT (System Under Test) DID operations.

This module provides endpoints for creating and managing DIDs for benchmark
executions and their iterations using the DIDService.
"""

import logging
from typing import Annotated, Any, Dict, List, Optional, cast

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_config
from app.database import MongoConnector
from app.did_utils.comparisons import compute_diff, has_diff
from app.routers.basetypes import CanonicalizedUUID, UUIDString, did_from_uuid
from app.routers.dependencies import EPDWTokenDep, APITokenDep401Response
from app.services.did_service import DIDServiceDep, ArtefactInput
from app.services.exceptions import (
    BenchmarkNotFoundError,
    IterationNotFoundError,
    NoIterationsFoundError,
    BlockedKeyUpdateError,
    NoChangesDetectedError,
    InvalidUpdaterEmailError,
    SUTRecordNotFoundError,
    DivisionMismatchError,
    VersionConflictError,
    ProvenanceNotFoundError,
)
from app.utils import clean_mongo_doc


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
    # EPDW is currently hooked to just send the BenchmarkExecutionId, *not* iterationID.
    # iterationID: Optional[UUIDString] = Field(
    #     default=None,
    #     description="Optional: Target a specific iteration (single-SUT mode)",
    #     json_schema_extra={"example": "43f418f6-3808-4e81-bf42-6e8d11def355"},
    # )


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
# Helper Functions
# ==========================
def _fetch_benchmark_doc(db: MongoConnector, benchmark_id: str) -> dict:
    """
    Fetch the full benchmark document from the source collection.

    Args:
        benchmark_id: The benchmarkExecutionID to fetch

    Returns:
        The benchmark document

    Raises:
        BenchmarkNotFoundError: If the benchmark is not found
    """
    config = get_config()
    qa_col = db.get_collection(config.collections.qa_benchmark_collection)
    doc = qa_col.find_one({"benchmarkExecutionID": benchmark_id})
    if not doc:
        raise BenchmarkNotFoundError(benchmark_id)
    return doc

def _fetch_iteration_doc(db: MongoConnector, iteration_id: str) -> dict:
    """
    Fetch the full benchmark iteration document from the source collection.

    Args:
        iteration_id: The iterationId to fetch

    Returns:
        The iteration document

    Raises:
        IterationNotFoundError: If the iteration is not found
    """
    config = get_config()
    qa_col = db.get_collection(config.collections.qa_benchmark_iterations)
    doc = qa_col.find_one({"iterationID": iteration_id})
    if not doc:
        raise IterationNotFoundError(iteration_id)
    return doc


def _extract_iterations(doc: dict) -> List[str]:
    """
    Extract iteration IDs from a benchmark document.

    Searches the nested structure: resultInfo -> runs -> iterations

    Args:
        doc: The benchmark document

    Returns:
        List of unique iteration IDs found
    """
    iterations = []

    # Primary extraction path: resultInfo -> runs -> iterations
    for ri in doc.get("resultInfo", []):
        for run in ri.get("runs", []):
            for it in run.get("iterations", []):
                if isinstance(it, dict) and "iterationID" in it:
                    iterations.append(it["iterationID"])

    # Fallback: deep search if primary path yields nothing
    if not iterations:
        def deep_find(obj):
            found = []
            if isinstance(obj, dict):
                if "iterationID" in obj and isinstance(obj["iterationID"], str):
                    found.append(obj["iterationID"])
                for v in obj.values():
                    found.extend(deep_find(v))
            elif isinstance(obj, list):
                for item in obj:
                    found.extend(deep_find(item))
            return found
        iterations = deep_find(doc)

    # Return unique values preserving order
    return list(dict.fromkeys(iterations))

def _clean_special_keys(doc: dict) -> dict:
    """
    Remove mongodb special fields from doc.
    """
    _KEYS_TO_CLEAN = frozenset({"_id"})
    for key in _KEYS_TO_CLEAN:
        if key in doc:
            del(doc[key])
    return doc

def _select_master_metadata(doc: dict):
    """
    Select fields from benchmark doc for master artefact metadata.

    Args:
        doc: The full benchmark document

    Returns:
        Selected metadata dictionary
    """
    return clean_mongo_doc(_clean_special_keys(doc)) # Alternative: *All* benchmark_execution data

    # Alternative: select key fields for the master artefact
    # return {
    #     "benchmarkExecutionID": doc.get("benchmarkExecutionID"),
    #     "benchmarkName": doc.get("benchmarkName"),
    #     "benchmarkVersion": doc.get("benchmarkVersion"),
    #     "systemInfo": doc.get("systemInfo"),
    #     "submissionDate": doc.get("submissionDate"),
    #     "resultInfo_count": len(doc.get("resultInfo", [])),
    # }

def _select_iteration_metadata(doc: dict):
    """
    Selects which metadata from an iteration document to include in the Digital
    Artefact (i.e. which fields will be locked down).
    """
    return clean_mongo_doc(_clean_special_keys(doc)) # All data.

def _validate_amd_email(email: str) -> None:
    """
    Validate that an email is an AMD email address.

    Args:
        email: The email to validate

    Raises:
        InvalidUpdaterEmailError: If not an @amd.com address
    """
    if not isinstance(email, str) or not email.lower().endswith("@amd.com"):
        raise InvalidUpdaterEmailError()


def _apply_updates(old_data: dict, incoming_data: dict) -> dict:
    """
    Apply incoming updates to existing data (deep merge).

    Args:
        old_data: The existing data
        incoming_data: The updates to apply

    Returns:
        The merged data
    """
    from copy import deepcopy
    result = deepcopy(old_data) if old_data else {}
    result = result | incoming_data # Python native merge.
    return result


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
    did_svc: DIDServiceDep
):
    """
    Create DIDs for a benchmark execution and its iterations.

    This endpoint creates:
    - A master DID for the benchmark execution
    - Child DIDs for each iteration (linked via provenance)

    The operation is idempotent - if DIDs already exist for the benchmark,
    the existing DIDs are returned.

    Args:
        req: Request containing benchmarkExecutionID and optional iterationID
        api_token: Validated API token (injected)
        did_svc: DID service instance (injected)

    Returns:
        JSON response with created/existing DIDs
    """
    benchmark_id = req.benchmarkExecutionID
    # iteration_id = req.iterationID

    # Check if master artefact already exists (idempotent)
    existing_master = did_svc.find_by_external_uid(
        external_uid=benchmark_id,
        division=_EPDW_DIVISION
    )

    if existing_master:
        # Master already exists - fetch all iterations and return
        master_did = did_from_uuid(existing_master.external_uid)

        # TODO: Do we need to check if the master document changed or if new
        # iterations have been added? Is that something that happens?

        # Find all child artefacts that have this benchmark as provenance
        children = did_svc.find_by_provenance(
            provenance_uid=benchmark_id,
            division=_EPDW_DIVISION
        )

        iterations = [
            {
                "iterationID": child.external_uid,
                "did": did_from_uuid(child.external_uid)
            }
            for child in children
        ]

        return JSONResponse({
            "status": "exists",
            "message": "Master DID already initialized",
            "benchmarkExecutionID": benchmark_id,
            "mode": "single" if len(iterations) == 1 else "multi",
            "master_did": master_did,
            "iterations": iterations,
        })

    # Fetch benchmark document from source collection
    doc = _fetch_benchmark_doc(did_svc.db, benchmark_id)

    # Extract iterations
    found_iterations = _extract_iterations(doc)
    if not found_iterations:
        raise NoIterationsFoundError(benchmark_id)

    # Determine mode
    mode = "single" if len(found_iterations) == 1 else "multi"

    # Create master artefact
    master_metadata = _select_master_metadata(doc)
    try:
        master_record = did_svc.upsert_artefact(ArtefactInput(
            external_uid=benchmark_id,
            division=_EPDW_DIVISION,
            artefact_metadata=master_metadata,
        ))
    except DivisionMismatchError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=str(e))
    except VersionConflictError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=str(e))

    master_did = did_from_uuid(master_record.external_uid)

    # Create child artefacts for each iteration
    iterations = []
    for iter_id in found_iterations:
        # Fetch iteration data and select specific metadata to add.
        iter_doc = _fetch_iteration_doc(did_svc.db, iter_id)
        iter_metadata = _select_iteration_metadata(iter_doc)
        try:
            child_record = did_svc.upsert_artefact(ArtefactInput(
                external_uid=iter_id,
                division=_EPDW_DIVISION,
                artefact_metadata=iter_metadata,
                provenance=[benchmark_id],  # Link to master
            ))
            iterations.append({
                "iterationID": iter_id,
                "did": did_from_uuid(child_record.external_uid)
            })
        except ProvenanceNotFoundError:
            # This shouldn't happen since we just created the master
            logger.error(f"Provenance error for iteration {iter_id}")
            raise
        except DivisionMismatchError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail=str(e))
        except VersionConflictError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail=str(e))

    logger.info(
        f"Created SUT DIDs: benchmark={benchmark_id}, "
        f"master_did={master_did}, iterations={len(iterations)}"
    )

    return JSONResponse({
        "status": "created",
        "benchmarkExecutionID": benchmark_id,
        "mode": mode,
        "master_did": master_did,
        "iterations": iterations,
    })


@app.post("/append-did",responses={**APITokenDep401Response, **NotFoundResponses})
async def append_did(
    body: DIDAppendRequest,
    api_token: EPDWTokenDep,
    did_svc: DIDServiceDep,
    update_message: str = Query(
        ...,
        description="Message describing the update",
        examples=["Adding new entitlement level"],
    ),
    updated_by: str = Query(
        ...,
        description="AMD email of the updater",
        examples=["user@amd.com"],
    ),
):
    """
    Append/update data to an existing iteration DID.

    Creates a new version of the artefact with the updated metadata.
    The diff between old and new data is computed and returned.

    Args:
        body: Request containing benchmarkExecutionID, iterationID, and data
        update_message: Description of the update
        updated_by: AMD email of the person making the update
        api_token: Validated API token
        did_svc: DID service instance

    Returns:
        JSON response with update details and diff
    """
    # Validate updater email
    _validate_amd_email(updated_by)

    benchmark_id = body.benchmarkExecutionID
    iteration_id = body.iterationID
    incoming_data = body.data or {}

    # Sanity check benchmark_id and iteration_id exist in the DB and are correct.
    # These functions raise an exception if the corresponding data item is not found.
    _fetch_benchmark_doc(did_svc.db, benchmark_id)
    _fetch_iteration_doc(did_svc.db, iteration_id)

    # Check for blocked keys (only on first level).
    _BLOCKED_KEYS = frozenset({"_id", "did", "benchmarkExecutionID", "iterationID"})
    for key in incoming_data:
        if key in _BLOCKED_KEYS:
            raise BlockedKeyUpdateError(key)

    # Find existing artefact
    existing = did_svc.find_by_external_uid(
        external_uid=iteration_id,
        division=_EPDW_DIVISION
    )

    if not existing:
        raise SUTRecordNotFoundError(benchmark_id, iteration_id)

    # Get existing metadata
    old_metadata = existing.artefact_metadata or {}
    previous_did = did_from_uuid(existing.external_uid)
    previous_version = existing.version

    # Apply updates
    new_metadata = _apply_updates(old_metadata, incoming_data)

    # Add update tracking info
    new_metadata["_last_update"] = {
        "message": update_message,
        "updated_by": updated_by,
        "previous_version": previous_version,
    }

    # Compute diff using shared comparison utility
    diff = cast(Dict[str, Any], compute_diff(old_metadata, new_metadata))

    # Check if there are actual changes
    if not has_diff(diff):
        raise NoChangesDetectedError()

    # Create new version via DIDService
    try:
        new_record = did_svc.upsert_artefact(ArtefactInput(
            external_uid=iteration_id,
            division=_EPDW_DIVISION,
            artefact_metadata=new_metadata,
            provenance=[benchmark_id],  # Maintain provenance link
        ))
    except DivisionMismatchError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=str(e))
    except VersionConflictError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=str(e))

    new_did = did_from_uuid(new_record.external_uid)

    logger.info(
        f"Updated SUT DID: iteration={iteration_id}, "
        f"version={new_record.version}, updated_by={updated_by}"
    )

    return {
        "status": "updated",
        "benchmarkExecutionID": benchmark_id,
        "iterationID": iteration_id,
        "did": new_did,
        "previous_did": previous_did if new_record.version > 1 else None,
        "version": new_record.version,
        "diff": diff,
        "message": "DID updated with authoritative deep JSON overwrite"
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
    example="95da4dd5-6e48-4c5b-bb91-935983c16d9c",
)]

@app.get("/epdw/{uid}/vc.json", responses={**APITokenDep401Response})
async def artefact_vc(
    uid: PathUUID,
    api_token: EPDWTokenDep,
    did_svc: DIDServiceDep,):
    """Return a Verifiable Credential with proofs for a Digital Artefact."""
    return did_svc.artefact_vc(division=_EPDW_DIVISION, uid=uid)
