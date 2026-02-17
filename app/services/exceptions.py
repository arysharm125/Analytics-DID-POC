"""Exceptions for DID service and related operations."""

from fastapi import HTTPException
from requests import HTTPError


_DID_PREFIX = "did:amd:com"


class DIDServiceError(Exception):
    """Base exception for DID service errors."""
    pass


class ValidationError(DIDServiceError, ValueError):
    """Base exception for validation errors (invalid identifiers, fields, etc.).

    These errors should typically result in HTTP 400 Bad Request responses.

    Note: This class also inherits from ValueError so that Pydantic validators
    (which expect ValueError or TypeError) properly catch these exceptions and
    return 422/400 responses instead of 500 errors.
    """
    pass


class InvalidIdentifierError(ValidationError):
    """Raised when an identifier is neither a valid UUID nor a valid DID."""

    def __init__(self, identifier: str):
        self.identifier = identifier
        super().__init__(
            f"Invalid identifier: '{identifier}'. Must be a valid UUID "
            f"(xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx) or DID ({_DID_PREFIX}:uuid)"
        )


class DuplicateProvenanceError(DIDServiceError, HTTPException):
    """Raised when duplicate identifiers are found in provenance after canonicalization."""

    def __init__(self):
        super().__init__(status_code=400, detail=
            "Duplicate identifiers found after canonicalization. "
            "Each provenance item must be unique."
        )


class DivisionMismatchError(DIDServiceError, HTTPException):
    """Raised when attempting to change an artefact's division."""

    def __init__(self, external_uid: str, existing_division: str, new_division: str):
        self.external_uid = external_uid
        self.existing_division = existing_division
        self.new_division = new_division
        detail = (
            f"Division mismatch for artefact '{external_uid}': "
            f"existing division is '{existing_division}', "
            f"but attempted to set '{new_division}'. Division cannot be changed."
        )
        super().__init__(status_code=409, detail=detail)


class VersionConflictError(DIDServiceError, HTTPException):
    """Raised when a concurrent update creates a version conflict."""

    def __init__(self, external_uid: str, version: int):
        self.external_uid = external_uid
        self.version = version
        detail = (
            f"Version conflict for artefact '{external_uid}': "
            f"version {version} already exists. This may indicate a concurrent update."
        )
        super().__init__(status_code=409, detail=detail)


class ProvenanceNotFoundError(DIDServiceError, HTTPException):
    """Raised when a provenance item references a non-existent artefact."""

    def __init__(self, identifier: str):
        self.identifier = identifier
        detail = f"Provenance item '{identifier}' does not exist in did_artefacts."
        super().__init__(status_code=409, detail=detail)


class InvalidMultihashError(ValidationError):
    """Raised when a multihash format is invalid."""

    def __init__(self, multihash: str, reason: str):
        self.multihash = multihash
        self.reason = reason
        super().__init__(f"Invalid multihash '{multihash}': {reason}")


class InvalidDivisionError(ValidationError):
    """Raised when a division identifier is invalid."""

    def __init__(self, division: str, reason: str):
        self.division = division
        self.reason = reason
        super().__init__(f"Invalid division '{division}': {reason}")

class ArtefactNotFoundError(DIDServiceError, HTTPException):
    """Raised when a DID/UUID fails to be fetched for a specified division."""
    def __init__(self, division: str | None, uid: str):
        self.division = division
        self.uid = uid
        detail = ""
        if division is None:
            detail = f"Artefact with uid '{uid}' not found in any division"
        else:
            f"Artefact with uid '{uid}' not found in division '{division}."

        super().__init__(status_code=404, detail=detail)


class DivisionKeysNotFound(DIDServiceError, HTTPException):
    """Raised when a division key is not found."""
    def __init__(self, division: str):
        self.division = division
        super().__init__(status_code=404, detail=f"Division keys for '{division}' not found.")


class ArtefactNoChangesError(DIDServiceError, HTTPException):
    """Raised when upserting an artefact with no actual changes.

    A new version requires at least one change to: artefact_hash,
    artefact_metadata (deep comparison), or provenance list.
    """
    def __init__(self, external_uid: str):
        self.external_uid = external_uid
        super().__init__(
            status_code=400,
            detail=(
                f"No changes detected for artefact '{external_uid}'. "
                "A new version requires changes to at least one of: "
                "artefact_hash, artefact_metadata, or provenance."
            )
        )


# =============================================================================
# SUT-specific Exceptions
# =============================================================================

class BenchmarkNotFoundError(DIDServiceError, HTTPException):
    """Raised when a benchmark execution ID is not found in the source data."""
    def __init__(self, benchmark_id: str):
        self.benchmark_id = benchmark_id
        super().__init__(status_code=404, detail=f"Benchmark '{benchmark_id}' not found")


class IterationNotFoundError(DIDServiceError, HTTPException):
    """Raised when an iteration is not found."""
    def __init__(self, iteration_id: str):
        self.iteration_id = iteration_id
        super().__init__(status_code=404, detail=f"Iteration '{iteration_id}' not found")


class NoIterationsFoundError(DIDServiceError, HTTPException):
    """Raised when no iterations exist under a benchmark."""
    def __init__(self, benchmark_id: str):
        self.benchmark_id = benchmark_id
        super().__init__(
            status_code=404,
            detail=f"No iterations found under benchmark '{benchmark_id}'"
        )


class BlockedKeyUpdateError(DIDServiceError, HTTPException):
    """Raised when attempting to update a protected key."""
    def __init__(self, key: str):
        self.key = key
        super().__init__(status_code=400, detail=f"Updates not allowed for key: {key}")


class NoChangesDetectedError(DIDServiceError, HTTPException):
    """Raised when an update payload contains no actual changes."""
    def __init__(self):
        super().__init__(status_code=400, detail="No changes detected in payload")


class InvalidUpdaterEmailError(DIDServiceError, HTTPException):
    """Raised when updater email is not a valid AMD email."""
    def __init__(self):
        super().__init__(status_code=400, detail="Unauthorized email — must be an @amd.com address")


class SUTRecordNotFoundError(DIDServiceError, HTTPException):
    """Raised when a SUT DID record is not found."""
    def __init__(self, benchmark_id: str, iteration_id: str):
        self.benchmark_id = benchmark_id
        self.iteration_id = iteration_id
        super().__init__(
            status_code=404,
            detail=f"Record not found for benchmark '{benchmark_id}', iteration '{iteration_id}'"
        )
