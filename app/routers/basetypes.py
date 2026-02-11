"""Base types for route requests and responses."""

import re
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator

# Generic DID format: did:<method>:<path>
# The pattern validates the basic DID structure per W3C DID spec
GENERIC_DID_PATTERN = re.compile(
    r"^did:"  # Fixed prefix
    r"[a-zA-Z0-9]+"  # Method (required, alphanumeric)
    r":.+$"  # Path (required, at least one character after method)
)

# AMD Web DID format: did:web:did.amd.com:division:optional:path:uuid
# The pattern breaks down as:
# - did:web:did.amd.com: - fixed prefix
# - division - required division slug (word characters)
# - optional path segments - zero or more path segments
# - uuid - UUID v4 at the end
AMD_WEB_DID_PATTERN = re.compile(
    r"^did:web:did\.amd\.com:"  # Fixed prefix
    r"[a-zA-Z0-9_-]+"  # Division (required)
    r"(?::[a-zA-Z0-9_-]+)*:"  # Optional path segments
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"  # UUID
)


def validate_did(value: str) -> str:
    """Validate that a string is a valid DID in the generic format did:<method>:<path>."""
    if not GENERIC_DID_PATTERN.match(value):
        raise ValueError(
            f"Invalid DID format: '{value}'. "
            "Expected format: did:<method>:<path>"
        )
    return value


def validate_amd_web_did(value: str) -> str:
    """Validate that a string is a valid AMD Web DID in the format did:web:did.amd.com:division:optional:path:uuid."""
    if not AMD_WEB_DID_PATTERN.match(value):
        raise ValueError(
            f"Invalid AMD Web DID format: '{value}'. "
            "Expected format: did:web:did.amd.com:division:optional:path:uuid"
        )
    return value


# Annotated type for generic DID validation (did:<method>:<path>)
DIDString = Annotated[str, AfterValidator(validate_did)]

# Annotated type for AMD Web DID validation (did:web:did.amd.com:...)
AMDWebDID = Annotated[str, AfterValidator(validate_amd_web_did)]


def validate_uuid(value: str) -> str:
    """Validate that a string is a valid UUID."""
    try:
        UUID(value)
    except ValueError as e:
        raise ValueError(f"Invalid UUID format: '{value}'") from e
    return value


# Annotated type for UUID validation
UUIDString = Annotated[str, AfterValidator(validate_uuid)]
