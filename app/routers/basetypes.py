"""Base types for route requests and responses."""

import re
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator

from app.services.exceptions import (
    DuplicateProvenanceError,
    InvalidIdentifierError,
    InvalidDivisionError,
    InvalidMultihashError,
)


# =============================================================================
# UUID Validation
# =============================================================================

# UUID v4 pattern for validation (reusable across models)
UUID_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
_UUID_REGEX = re.compile(UUID_PATTERN)


def validate_uuid(value: str) -> str:
    """Validate that a string is a valid UUID."""
    try:
        UUID(value)
    except ValueError as e:
        raise ValueError(f"Invalid UUID format: '{value}'") from e
    return value


# Annotated type for UUID validation
UUIDString = Annotated[str, AfterValidator(validate_uuid)]


# =============================================================================
# Generic DID Validation
# =============================================================================

# Generic DID format: did:<method>:<path>
# The pattern validates the basic DID structure per W3C DID spec
GENERIC_DID_PATTERN = re.compile(
    r"^did:"  # Fixed prefix
    r"[a-zA-Z0-9]+"  # Method (required, alphanumeric)
    r":.+$"  # Path (required, at least one character after method)
)


def validate_did(value: str) -> str:
    """Validate that a string is a valid DID in the generic format did:<method>:<path>."""
    if not GENERIC_DID_PATTERN.match(value):
        raise ValueError(
            f"Invalid DID format: '{value}'. "
            "Expected format: did:<method>:<path>"
        )
    return value


# Annotated type for generic DID validation (did:<method>:<path>)
DIDString = Annotated[str, AfterValidator(validate_did)]


# =============================================================================
# AMD Web DID Validation
# =============================================================================

# Fixed prefix for AMD-based web DIDs.
_AMD_WEB_DID_PREFIX = "did:web:did.amd.com:"

# AMD Web DID format: did:web:did.amd.com:uuid
# The pattern breaks down as:
# - did:web:did.amd.com: - fixed prefix
# - uuid - UUID v4 at the end (no division or path segments allowed)
_AMD_WEB_DID_PATTERN = re.compile(
    r"^did:web:did\.amd\.com:"  # Fixed prefix
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"  # UUID (captured in group 1)
)


def validate_amd_web_did(value: str) -> str:
    """Validate that a string is a valid AMD Web DID in the format did:web:did.amd.com:uuid."""
    if not _AMD_WEB_DID_PATTERN.match(value):
        raise ValueError(
            f"Invalid AMD Web DID format: '{value}'. "
            "Expected format: did:web:did.amd.com:uuid"
        )
    return value


# Annotated type for AMD Web DID validation (did:web:did.amd.com:...)
AMDWebDID = Annotated[str, AfterValidator(validate_amd_web_did)]


def did_from_uuid(uuid: UUIDString) -> AMDWebDID:
    """
    Build a DID string from a UUID string.

    Args:
        uuid: The UUID component of the DID (validated UUID string)

    Returns:
        The DID string (e.g., "did:web:did.amd.com:uuid") as AMDWebDID type
    """
    return f"{_AMD_WEB_DID_PREFIX}{uuid}"


def uuid_from_did(did: AMDWebDID) -> UUIDString:
    """
    Extract the UUID from a DID string.

    Args:
        did: A DID in the format did:web:did.amd.com:...:uuid (AMDWebDID type or string)

    Returns:
        The UUID portion of the DID as a validated UUID string

    Raises:
        ValueError: If the DID format is invalid
    """
    match = _AMD_WEB_DID_PATTERN.match(did)
    if not match:
        raise ValueError(f"Invalid AMD DID format: '{did}'. Expected format: {_AMD_WEB_DID_PREFIX}uuid")
    return match.group(1)


def _validate_did_or_uuid(value: str) -> str:
    """
    Validate that a string is either a valid UUID or a valid DID (did:amd:com:uuid).

    Args:
        value: The string to validate

    Returns:
        The validated string (unchanged)

    Raises:
        InvalidIdentifierError: If the string is neither a valid UUID nor a valid DID
    """
    # Check if it's a UUID
    if _UUID_REGEX.match(value):
        return value
    # Check if it's a DID
    if _AMD_WEB_DID_PATTERN.match(value):
        return value
    raise InvalidIdentifierError(value)


def _canonicalize_did_or_uuid(value: str) -> str:
    """
    Canonicalize a DID or UUID to just the UUID portion.

    DIDs in the format did:amd:com:uuid are converted to just the uuid.
    UUIDs are returned unchanged.

    Args:
        value: A validated DID or UUID string

    Returns:
        The UUID portion of the identifier
    """
    match = _AMD_WEB_DID_PATTERN.match(value)
    if match:
        return match.group(1)
    return value


def _validate_and_canonicalize_did_or_uuid(value: str) -> str:
    """
    Validate and canonicalize a DID or UUID.

    First validates the input is either a DID or UUID, then canonicalizes
    to just the UUID portion.

    Args:
        value: The string to validate and canonicalize

    Returns:
        The canonicalized UUID string
    """
    _validate_did_or_uuid(value)
    return _canonicalize_did_or_uuid(value)


# Type for a single DID or UUID identifier (validated but not canonicalized)
DIDOrUUID = Annotated[str, AfterValidator(_validate_did_or_uuid)]

# Type for a single DID or UUID identifier (validated AND canonicalized to UUID)
CanonicalizedUUID = Annotated[str, AfterValidator(_validate_and_canonicalize_did_or_uuid)]


def _validate_did_or_uuid_list(values: list[str]) -> list[str]:
    """
    Validate and canonicalize a list of DID or UUID identifiers.

    Each item is validated to be either a DID or UUID, then canonicalized
    to just the UUID portion. The resulting list is returned.

    Args:
        values: List of DID or UUID strings

    Returns:
        List of canonicalized UUID strings

    Raises:
        InvalidIdentifierError: If any item is not a valid UUID or DID
        DuplicateProvenanceError: If there are duplicates after canonicalization
    """
    canonicalized = []
    for value in values:
        canonical = _validate_and_canonicalize_did_or_uuid(value)
        canonicalized.append(canonical)

    # Check for duplicates after canonicalization
    if len(canonicalized) != len(set(canonicalized)):
        raise DuplicateProvenanceError()

    return canonicalized


# Type for a list of DID or UUID identifiers (validated and canonicalized)
DIDOrUUIDList = Annotated[list[str], AfterValidator(_validate_did_or_uuid_list)]


def _validate_did_list(values: list[str]) -> list[str]:
    """
    Validate a list of AMD Web DID identifiers.

    Each item is validated to be a valid AMD Web DID. The resulting list is returned.

    Args:
        values: List of AMD Web DID strings

    Returns:
        List of validated AMD Web DID strings

    Raises:
        ValueError: If any item is not a valid AMD Web DID
        DuplicateProvenanceError: If there are duplicate DIDs
    """
    validated = []
    for value in values:
        validate_amd_web_did(value)
        validated.append(value)

    # Check for duplicates
    if len(validated) != len(set(validated)):
        raise DuplicateProvenanceError()

    return validated


# Type for a list of AMD Web DIDs
DIDList = Annotated[list[str], AfterValidator(_validate_did_list)]


def did_list_from_uuid_list(uuids: list[UUIDString]) -> DIDList:
    """
    Convert a list of UUIDs to a list of DIDs.

    Args:
        uuids: List of UUID strings (typically from DIDOrUUIDList which canonicalizes to UUIDs)

    Returns:
        List of AMD Web DID strings
    """
    return [did_from_uuid(uuid) for uuid in uuids]


# =============================================================================
# Multihash Validation
# =============================================================================

# Base58btc alphabet (no 0, O, I, l to avoid ambiguity)
_BASE58BTC_ALPHABET = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")

# SHA-256 multihash constants
# Base58btc-encoded SHA-256 multihash starts with "Qm" and is exactly 46 characters
# Format: 0x12 (sha2-256 code) + 0x20 (32 bytes length) + 32-byte digest
_SHA256_MULTIHASH_PREFIX = "Qm"
_SHA256_MULTIHASH_LENGTH = 46


def _validate_multihash(value: str) -> str:
    """
    Validate that a string is a valid SHA-256 multihash format.

    Only SHA-256 multihashes are currently supported. Base58btc-encoded SHA-256
    multihashes start with 'Qm' and are exactly 46 characters long.

    Args:
        value: The string to validate

    Returns:
        The validated string (unchanged)

    Raises:
        InvalidMultihashError: If the string is not a valid SHA-256 multihash format
    """
    if not value:
        raise InvalidMultihashError(value, "Multihash cannot be empty")

    # Validate base58btc alphabet
    invalid_chars = set(value) - _BASE58BTC_ALPHABET
    if invalid_chars:
        raise InvalidMultihashError(
            value,
            f"contains characters not in base58btc alphabet: {sorted(invalid_chars)}"
        )

    # Validate SHA-256 multihash format (only supported hash function for now)
    if not value.startswith(_SHA256_MULTIHASH_PREFIX):
        raise InvalidMultihashError(
            value,
            f"only SHA-256 multihashes are supported (must start with '{_SHA256_MULTIHASH_PREFIX}')"
        )

    if len(value) != _SHA256_MULTIHASH_LENGTH:
        raise InvalidMultihashError(
            value,
            f"SHA-256 multihash must be exactly {_SHA256_MULTIHASH_LENGTH} characters, got {len(value)}"
        )

    return value


# Annotated type for multihash validation (base58btc-encoded SHA-256 multihash)
Multihash = Annotated[str, AfterValidator(_validate_multihash)]

def multihash_from_str(s : str) -> Multihash:
    _validate_multihash(s)
    return s

# =============================================================================
# Division String Validation
# =============================================================================

# Division pattern: single word with lowercase ASCII letters, digits, and underscores
# Must start with a letter, not a digit or underscore
_DIVISION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

def _validate_division(value: str) -> str:
    """
    Validate that a string is a valid division identifier.

    A valid division is a single word containing only lowercase ASCII letters,
    digits, and underscores. It must start with a lowercase letter.

    Args:
        value: The string to validate

    Returns:
        The validated string (unchanged)

    Raises:
        InvalidDivisionError: If the string is not a valid division format
    """
    if not value:
        raise InvalidDivisionError(value, "Division cannot be empty")

    if not _DIVISION_PATTERN.match(value):
        raise InvalidDivisionError(
            value,
            "must contain only lowercase ASCII letters, digits, and underscores, "
            "and must start with a letter"
        )

    return value


# Annotated type for division validation (lowercase ASCII word with underscores)
DivisionStr = Annotated[str, AfterValidator(_validate_division)]


def division_from_str(s: str) -> DivisionStr:
    """Convert and validate a string to DivisionStr type."""
    _validate_division(s)
    return s


# =============================================================================
# AMD Division Web DID Validation
# =============================================================================

# Fixed prefix for AMD Division-based web DIDs.
_AMD_DIVISION_WEB_DID_PREFIX = "did:web:did.amd.com:"

# AMD Division Web DID format: did:web:did.amd.com:<division>
# The pattern breaks down as:
# - did:web:did.amd.com: - fixed prefix
# - division - lowercase ASCII letters, digits, and underscores, starting with a letter
_AMD_DIVISION_WEB_DID_PATTERN = re.compile(
    r"^did:web:did\.amd\.com:"  # Fixed prefix
    r"([a-z][a-z0-9_]*)$"  # Division (captured in group 1)
)


def validate_amd_division_web_did(value: str) -> str:
    """Validate that a string is a valid AMD Division Web DID in the format did:web:did.amd.com:<division>."""
    match = _AMD_DIVISION_WEB_DID_PATTERN.match(value)
    if not match:
        raise ValueError(
            f"Invalid AMD Division Web DID format: '{value}'. "
            "Expected format: did:web:did.amd.com:<division> where division contains only "
            "lowercase ASCII letters, digits, and underscores, and starts with a letter"
        )
    return value


# Annotated type for AMD Division Web DID validation (did:web:did.amd.com:<division>)
AMDDivisionWebDID = Annotated[str, AfterValidator(validate_amd_division_web_did)]


def division_did_from_division(division: DivisionStr) -> AMDDivisionWebDID:
    """
    Build a Division DID string from a division string.

    Args:
        division: The division component of the DID (validated division string)

    Returns:
        The DID string (e.g., "did:web:did.amd.com:division") as AMDDivisionWebDID type
    """
    return f"{_AMD_DIVISION_WEB_DID_PREFIX}{division}"


def division_from_division_did(did: AMDDivisionWebDID) -> DivisionStr:
    """
    Extract the division from a Division DID string.

    Args:
        did: A DID in the format did:web:did.amd.com:<division> (AMDDivisionWebDID type or string)

    Returns:
        The division portion of the DID as a validated DivisionStr

    Raises:
        ValueError: If the DID format is invalid
    """
    match = _AMD_DIVISION_WEB_DID_PATTERN.match(did)
    if not match:
        raise ValueError(
            f"Invalid AMD Division DID format: '{did}'. "
            f"Expected format: {_AMD_DIVISION_WEB_DID_PREFIX}<division>"
        )
    return match.group(1)
