"""Exceptions for DID service and related operations."""

from fastapi import HTTPException

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
    """
    Raised when attempting to change an artefact's division or trying to find
    an artefact of the wrong division.
    """

    def __init__(self, external_uid: str, existing_division: str, target_division: str):
        self.external_uid = external_uid
        self.existing_division = existing_division
        self.target_division = target_division
        detail = (
            f"Division mismatch for artefact '{external_uid}': "
            f"existing division is '{existing_division}', "
            f"but target division is '{target_division}'. Division cannot be changed."
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


class RecommendationNotFoundError(DIDServiceError, HTTPException):
    """Raised when a recommendation UID doesn't exist or isn't of type 'recommendation' in advisory division."""

    def __init__(self, recommendation_uid: str):
        self.recommendation_uid = recommendation_uid
        detail = (
            f"Recommendation '{recommendation_uid}' not found or is not of type 'recommendation' "
            "in the advisory division."
        )
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


class InvalidArtefactTypeError(ValidationError):
    """Raised when an artefact type identifier is invalid."""

    def __init__(self, artefact_type: str, reason: str):
        self.artefact_type = artefact_type
        self.reason = reason
        super().__init__(f"Invalid artefact type '{artefact_type}': {reason}")

class ArtefactNotFoundError(DIDServiceError, HTTPException):
    """Raised when a DID/UUID fails to be fetched for a specified division."""
    def __init__(self, division: str | None, uid: str):
        self.division = division
        self.uid = uid
        detail = ""
        if division is None:
            detail = f"Artefact with uid '{uid}' not found in any division"
        else:
            detail = f"Artefact with uid '{uid}' not found in division '{division}."

        super().__init__(status_code=404, detail=detail)


class DivisionKeysNotFoundError(DIDServiceError, HTTPException):
    """Raised when a division key is not found."""
    def __init__(self, division: str):
        self.division = division
        super().__init__(status_code=404, detail=f"Division keys for '{division}' not found.")


class SecretNotFoundError(DIDServiceError):
    """Raised when a secret is not found in vault.

    This exception is used by all VaultClientProtocol implementations to provide
    a consistent error type when a secret doesn't exist at the specified path.
    """
    def __init__(self, mount_point: str, path: str):
        self.mount_point = mount_point
        self.path = path
        super().__init__(f"Secret not found at {mount_point}/{path}")


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
# VC Issuance Exceptions
# =============================================================================

class VCAlreadyExistsError(DIDServiceError, HTTPException):
    """Raised when attempting to issue a VC for a DA version that already has one."""
    def __init__(self, version_uid: str):
        self.version_uid = version_uid
        super().__init__(
            status_code=409,
            detail=f"A VC has already been issued for artefact version '{version_uid}'."
        )


class VCNotFoundError(DIDServiceError, HTTPException):
    """Raised when a VC is not found."""
    def __init__(self, version_uid: str):
        self.version_uid = version_uid
        super().__init__(
            status_code=404,
            detail=f"No VC found for artefact version '{version_uid}'."
        )


class VCRegenerationMismatchError(DIDServiceError):
    """Raised when regenerated VC doesn't match stored VC.

    This is a non-HTTP exception used internally for verification purposes.
    """
    def __init__(self, version_uid: str, details: str = ""):
        self.version_uid = version_uid
        message = f"Regenerated VC for version '{version_uid}' does not match stored VC"
        if details:
            message += f": {details}"
        super().__init__(message)


class SigningKeyNotAvailableError(DIDServiceError, HTTPException):
    """Raised when a specific signing key fragment is not available in vault."""
    def __init__(self, division: str, fragment: str):
        self.division = division
        self.fragment = fragment
        super().__init__(
            status_code=404,
            detail=f"Signing key '{fragment}' not found for division '{division}'."
        )


class InvalidUpdaterEmailError(DIDServiceError, HTTPException):
    """Raised when updater email is not a valid AMD email."""
    def __init__(self):
        super().__init__(status_code=400, detail="Unauthorized email — must be an @amd.com address")


class DuplicateIterationIdsError(DIDServiceError, HTTPException):
    """Raised when duplicate iteration IDs are found in a benchmark request."""
    def __init__(self, duplicate_ids: list[str]):
        self.duplicate_ids = duplicate_ids
        super().__init__(
            status_code=400,
            detail=f"Duplicate iteration IDs found: {', '.join(duplicate_ids)}"
        )


class IterationIdMatchesBenchmarkIdError(DIDServiceError, HTTPException):
    """Raised when an iteration ID matches the benchmark ID."""
    def __init__(self, iteration_ids: list[str]):
        self.iteration_ids = iteration_ids
        super().__init__(
            status_code=400,
            detail=f"Iteration IDs cannot match benchmark ID: {', '.join(iteration_ids)}"
        )


class DifferentArtefactError(DIDServiceError, HTTPException):
    """Raised when attempting to compare versions of different artefacts."""
    def __init__(self, source_uid: str, target_uid: str):
        self.source_uid = source_uid
        self.target_uid = target_uid
        super().__init__(
            status_code=400,
            detail=f"Cannot compare versions from different artefacts: '{source_uid}' and '{target_uid}' belong to different artefacts"
        )


class DuplicateExternalUidsError(DIDServiceError, HTTPException):
    """Raised when duplicate external UIDs are found in an update request."""
    def __init__(self, duplicate_uids: list[str]):
        self.duplicate_uids = duplicate_uids
        super().__init__(
            status_code=400,
            detail=f"Duplicate external UIDs found: {', '.join(duplicate_uids)}"
        )


# Backward compatibility alias
DuplicateArtefactUidsError = DuplicateExternalUidsError


class ArtefactsNotFoundError(DIDServiceError, HTTPException):
    """Raised when one or more artefacts are not found in the specified division."""
    def __init__(self, missing_uids: list[str], division: str = "epdw"):
        self.missing_uids = missing_uids
        self.division = division
        super().__init__(
            status_code=404,
            detail=f"Artefacts not found in division '{division}': {', '.join(missing_uids)}"
        )


class CSResponseParseError(DIDServiceError, HTTPException):
    """Raised when CS API response cannot be parsed into expected structure."""
    def __init__(self, details: str = ""):
        detail = "Failed to parse CS API response"
        if details:
            detail += f": {details}"
        super().__init__(status_code=500, detail=detail)
