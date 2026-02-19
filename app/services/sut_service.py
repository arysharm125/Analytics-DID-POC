"""Service layer for SUT (System Under Test) DID operations."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Optional, cast

from fastapi import Depends

from app.config import get_config
from app.database import MongoConnector
from app.did_utils.comparisons import compute_diff, has_diff
from app.routers.basetypes import UUIDString, did_from_uuid
from app.services.did_service import DIDService, DIDServiceDep, ArtefactInput
from app.services.exceptions import (
    BenchmarkNotFoundError,
    IterationNotFoundError,
    NoIterationsFoundError,
    BlockedKeyUpdateError,
    NoChangesDetectedError,
    InvalidUpdaterEmailError,
    SUTRecordNotFoundError,
)
from app.utils import clean_mongo_doc


# ==========================
# Constants
# ==========================
_EPDW_DIVISION = "epdw"
_BLOCKED_KEYS = frozenset({"_id", "did", "benchmarkExecutionID", "iterationID"})
_KEYS_TO_CLEAN = frozenset({"_id"})


# ==========================
# Data Classes
# ==========================
@dataclass
class IterationDIDInfo:
    """Information about a created iteration DID."""
    iteration_id: str
    did: str


@dataclass
class CreateSutResult:
    """Result of creating SUT DIDs."""
    status: str  # "created" or "exists"
    benchmark_id: str
    mode: str  # "single" or "multi"
    master_did: str
    iterations: List[IterationDIDInfo]
    message: Optional[str] = None


@dataclass
class AppendDIDResult:
    """Result of appending data to a DID."""
    status: str
    benchmark_id: str
    iteration_id: str
    did: str
    previous_did: Optional[str]
    version: int
    diff: Dict[str, Any]
    message: str


# ==========================
# Helper Functions (Pure)
# ==========================
def extract_iterations(doc: dict) -> List[str]:
    """Extract iteration IDs from a benchmark document.

    Searches the nested structure: resultInfo -> runs -> iterations

    Args:
        doc: The benchmark document

    Returns:
        List of unique iteration IDs found
    """
    iterations: List[str] = []

    # Primary extraction path: resultInfo -> runs -> iterations
    for ri in doc.get("resultInfo", []):
        for run in ri.get("runs", []):
            for it in run.get("iterations", []):
                if isinstance(it, dict) and "iterationID" in it:
                    iterations.append(it["iterationID"])

    # Fallback: deep search if primary path yields nothing
    if not iterations:
        iterations = _deep_find_iterations(doc)

    # Return unique values preserving order
    return list(dict.fromkeys(iterations))


def _deep_find_iterations(obj: Any) -> List[str]:
    """Recursively search for iterationID fields."""
    found: List[str] = []
    if isinstance(obj, dict):
        if "iterationID" in obj and isinstance(obj["iterationID"], str):
            found.append(obj["iterationID"])
        for v in obj.values():
            found.extend(_deep_find_iterations(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_deep_find_iterations(item))
    return found


def clean_special_keys(doc: dict) -> dict:
    """Remove MongoDB special fields from doc.

    Args:
        doc: Document to clean

    Returns:
        Document with special keys removed
    """
    return {k: v for k, v in doc.items() if k not in _KEYS_TO_CLEAN}


def select_master_metadata(doc: dict) -> dict:
    """Select fields from benchmark doc for master artefact metadata.

    Args:
        doc: The full benchmark document

    Returns:
        Selected metadata dictionary (cleaned for JSON serialization)
    """
    result = clean_mongo_doc(clean_special_keys(doc))
    return cast(dict, result)


def select_iteration_metadata(doc: dict) -> dict:
    """Select which metadata from an iteration document to include in the Digital Artefact.

    Args:
        doc: The iteration document

    Returns:
        Selected metadata dictionary (cleaned for JSON serialization)
    """
    result = clean_mongo_doc(clean_special_keys(doc))
    return cast(dict, result)


def validate_amd_email(email: str) -> None:
    """Validate that an email is an AMD email address.

    Args:
        email: The email to validate

    Raises:
        InvalidUpdaterEmailError: If not an @amd.com address
    """
    if not isinstance(email, str) or not email.lower().endswith("@amd.com"):
        raise InvalidUpdaterEmailError()


def validate_no_blocked_keys(data: dict) -> None:
    """Validate that data doesn't contain blocked keys.

    Args:
        data: The data to validate

    Raises:
        BlockedKeyUpdateError: If a blocked key is found
    """
    for key in data:
        if key in _BLOCKED_KEYS:
            raise BlockedKeyUpdateError(key)


def apply_updates(old_data: dict, incoming_data: dict) -> dict:
    """Apply incoming updates to existing data (shallow merge).

    Uses Python's native dict merge (|) operator for shallow merging.

    Args:
        old_data: The existing data
        incoming_data: The updates to apply

    Returns:
        The merged data
    """
    result = deepcopy(old_data) if old_data else {}
    return result | incoming_data


# ==========================
# Service Class
# ==========================
class SUTService:
    """Service for SUT (System Under Test) DID operations.

    This class contains the business logic for:
    - Creating master DIDs for benchmark executions
    - Creating child DIDs for iterations
    - Appending/updating iteration data

    It is designed to be easily testable by accepting dependencies
    via constructor injection.

    Example usage:
        # In production (via FastAPI dependency injection)
        @router.post("/create-sut-did")
        def create_sut_did(sut_svc: SUTServiceDep):
            result = sut_svc.create_sut_dids(benchmark_id)
            return result

        # In tests
        mock_db = MongoConnector.from_client(mongomock.MongoClient(), "test")
        mock_did_svc = DIDService(db=mock_db, vault_svc=mock_vault)
        sut_svc = SUTService(db=mock_db, did_svc=mock_did_svc)
        result = sut_svc.create_sut_dids("test-benchmark-id")
    """

    def __init__(self, db: MongoConnector, did_svc: DIDService):
        """Initialize the SUT service.

        Args:
            db: Database connector for accessing source collections
            did_svc: DID service for artefact management
        """
        self._db = db
        self._did_svc = did_svc
        config = get_config()
        self._qa_collection = config.collections.qa_benchmark_collection
        self._qa_iter_collection = config.collections.qa_benchmark_iterations

    # ========================
    # Data Access Methods
    # ========================

    def fetch_benchmark(self, benchmark_id: str) -> dict:
        """Fetch a benchmark document from the source collection.

        Args:
            benchmark_id: The benchmarkExecutionID to fetch

        Returns:
            The benchmark document

        Raises:
            BenchmarkNotFoundError: If the benchmark is not found
        """
        collection = self._db.get_collection(self._qa_collection)
        doc = collection.find_one({"benchmarkExecutionID": benchmark_id})
        if not doc:
            raise BenchmarkNotFoundError(benchmark_id)
        return doc

    def fetch_iteration(self, iteration_id: str) -> dict:
        """Fetch an iteration document from the source collection.

        Args:
            iteration_id: The iterationID to fetch

        Returns:
            The iteration document

        Raises:
            IterationNotFoundError: If the iteration is not found
        """
        collection = self._db.get_collection(self._qa_iter_collection)
        doc = collection.find_one({"iterationID": iteration_id})
        if not doc:
            raise IterationNotFoundError(iteration_id)
        return doc

    # ========================
    # Main Operations
    # ========================

    def create_sut_dids(self, benchmark_id: UUIDString) -> CreateSutResult:
        """Create DIDs for a benchmark execution and its iterations.

        This operation is idempotent - if DIDs already exist for the benchmark,
        the existing DIDs are returned.

        Args:
            benchmark_id: The benchmark execution ID

        Returns:
            CreateSutResult with created/existing DIDs

        Raises:
            BenchmarkNotFoundError: If benchmark not found
            NoIterationsFoundError: If no iterations in benchmark
        """
        # Check if master artefact already exists (idempotent)
        existing_master = self._did_svc.find_by_external_uid(
            external_uid=benchmark_id,
            division=_EPDW_DIVISION
        )

        if existing_master:
            return self._get_existing_sut_result(benchmark_id, existing_master)

        return self._create_new_sut_dids(benchmark_id)

    def _get_existing_sut_result(
        self, benchmark_id: str, existing_master
    ) -> CreateSutResult:
        """Build result for existing SUT DIDs.

        Args:
            benchmark_id: The benchmark execution ID
            existing_master: The existing master artefact record

        Returns:
            CreateSutResult with existing DID information
        """
        master_did = did_from_uuid(existing_master.external_uid)

        # Find all child artefacts that have this benchmark as provenance
        children = self._did_svc.find_by_provenance(
            provenance_uid=benchmark_id,
            division=_EPDW_DIVISION
        )

        iterations = [
            IterationDIDInfo(
                iteration_id=child.external_uid,
                did=did_from_uuid(child.external_uid)
            )
            for child in children
        ]

        return CreateSutResult(
            status="exists",
            benchmark_id=benchmark_id,
            mode="single" if len(iterations) == 1 else "multi",
            master_did=master_did,
            iterations=iterations,
            message="Master DID already initialized",
        )

    def _create_new_sut_dids(self, benchmark_id: str) -> CreateSutResult:
        """Create new SUT DIDs for a benchmark.

        Args:
            benchmark_id: The benchmark execution ID

        Returns:
            CreateSutResult with newly created DID information

        Raises:
            BenchmarkNotFoundError: If benchmark not found
            NoIterationsFoundError: If no iterations in benchmark
        """
        # Fetch benchmark document from source collection
        doc = self.fetch_benchmark(benchmark_id)

        # Extract iterations
        found_iterations = extract_iterations(doc)
        if not found_iterations:
            raise NoIterationsFoundError(benchmark_id)

        mode = "single" if len(found_iterations) == 1 else "multi"

        # Create master artefact
        master_metadata = select_master_metadata(doc)
        master_record = self._did_svc.upsert_artefact(ArtefactInput(
            external_uid=benchmark_id,
            division=_EPDW_DIVISION,
            artefact_metadata=master_metadata,
        ))
        master_did = did_from_uuid(master_record.external_uid)

        # Create child artefacts for each iteration
        iterations: List[IterationDIDInfo] = []
        for iter_id in found_iterations:
            iter_doc = self.fetch_iteration(iter_id)
            iter_metadata = select_iteration_metadata(iter_doc)

            child_record = self._did_svc.upsert_artefact(ArtefactInput(
                external_uid=iter_id,
                division=_EPDW_DIVISION,
                artefact_metadata=iter_metadata,
                provenance=[benchmark_id],
            ))
            iterations.append(IterationDIDInfo(
                iteration_id=iter_id,
                did=did_from_uuid(child_record.external_uid)
            ))

        return CreateSutResult(
            status="created",
            benchmark_id=benchmark_id,
            mode=mode,
            master_did=master_did,
            iterations=iterations,
        )

    def append_to_iteration(
        self,
        benchmark_id: UUIDString,
        iteration_id: UUIDString,
        data: Dict[str, Any],
        update_message: str,
        updated_by: str,
    ) -> AppendDIDResult:
        """Append/update data to an existing iteration DID.

        Creates a new version of the artefact with the updated metadata.
        The diff between old and new data is computed and returned.

        Args:
            benchmark_id: The benchmark execution ID
            iteration_id: The iteration ID to update
            data: The data to merge/update
            update_message: Description of the update
            updated_by: AMD email of the updater

        Returns:
            AppendDIDResult with update details

        Raises:
            InvalidUpdaterEmailError: If email is not @amd.com
            BenchmarkNotFoundError: If benchmark not found
            IterationNotFoundError: If iteration not found
            BlockedKeyUpdateError: If trying to update protected key
            SUTRecordNotFoundError: If no DID record exists
            NoChangesDetectedError: If no actual changes in data
        """
        # Validate inputs
        validate_amd_email(updated_by)
        validate_no_blocked_keys(data)

        # Verify source documents exist
        self.fetch_benchmark(benchmark_id)
        self.fetch_iteration(iteration_id)

        # Find existing artefact
        existing = self._did_svc.find_by_external_uid(
            external_uid=iteration_id,
            division=_EPDW_DIVISION
        )

        if not existing:
            raise SUTRecordNotFoundError(benchmark_id, iteration_id)

        # Prepare update
        old_metadata = existing.artefact_metadata or {}
        previous_did = did_from_uuid(existing.external_uid)
        previous_version = existing.version

        # Apply updates
        new_metadata = apply_updates(old_metadata, data)
        new_metadata["_last_update"] = {
            "message": update_message,
            "updated_by": updated_by,
            "previous_version": previous_version,
        }

        # Compute diff using shared comparison utility
        diff = cast(Dict[str, Any], compute_diff(old_metadata, new_metadata))

        if not has_diff(diff):
            raise NoChangesDetectedError()

        # Create new version via DIDService
        new_record = self._did_svc.upsert_artefact(ArtefactInput(
            external_uid=iteration_id,
            division=_EPDW_DIVISION,
            artefact_metadata=new_metadata,
            provenance=[benchmark_id],
        ))

        return AppendDIDResult(
            status="updated",
            benchmark_id=benchmark_id,
            iteration_id=iteration_id,
            did=did_from_uuid(new_record.external_uid),
            previous_did=previous_did if new_record.version > 1 else None,
            version=new_record.version,
            diff=diff,
            message="DID updated with authoritative deep JSON overwrite",
        )


# ==========================
# FastAPI Dependency Injection
# ==========================

def _get_sut_service(did_svc: DIDServiceDep) -> SUTService:
    """FastAPI dependency to get SUTService instance.

    Args:
        did_svc: DIDService instance (injected via DIDServiceDep)

    Returns:
        SUTService instance
    """
    return SUTService(db=did_svc.db, did_svc=did_svc)


# Type alias for SUTService dependency injection
SUTServiceDep = Annotated[SUTService, Depends(_get_sut_service)]
