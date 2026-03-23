from __future__ import annotations

import gzip
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003
from typing import Any, ClassVar

from fastapi import HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.database import MigrationSet, MongoConnector
from app.did_utils.comparisons import deep_equals
from app.did_utils.eddsa import sign_vc
from app.did_utils.jsonld import DigitalArtefactVCInput, generate_digital_artefact_vc
from app.routers.basetypes import (
    ArtefactTypeStr,
    CanonicalizedUUID,
    DIDOrUUIDList,
    DivisionStr,
    Multihash,
    UUIDString,
    division_did_from_division,
    division_from_str,
)
from app.services.exceptions import (
    ArtefactNoChangesError,
    ArtefactNotFoundError,
    DivisionKeysNotFoundError,
    DivisionMismatchError,
    ProvenanceNotFoundError,
    VersionConflictError,
)
from app.services.vault_service import (
    DivisionPublicKeysNotFoundError,
    SigningKeyNotFoundError,
    VaultService,
)

# =============================================================================
# Logging
# =============================================================================
logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================
_default_format_version = 1


# =============================================================================
# Input Models
# =============================================================================
class ArtefactInput(BaseModel):
    """Input model for upserting an artefact. Does not include 'revoked' field."""
    external_uid: UUIDString = Field(
        ...,
        description="UUID identifying the artefact across versions"
    )
    division: DivisionStr = Field(..., description="Division identifier")
    artefact_hash: Multihash | None = Field(default=None, description="Multihash identifying artefact content")
    artefact_metadata: Any | None = Field(default=None, description="Optional JSON metadata for the artefact")
    artefact_type: ArtefactTypeStr | None = Field(default=None, description="Optional artefact type identifier")
    backlink: str | None = Field(default=None, description="Optional URL back to the object in the originating system")
    provenance: DIDOrUUIDList | None = Field(
        default=None,
        description="Optional list of provenance identifiers (UUIDs or DIDs). "
                    "Each item is validated and canonicalized to UUID format."
    )
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    update_message: str | None = Field(default=None, description="Optional message describing this update")
    updated_by: str | None = Field(default=None, description="Optional email of the person who made this update")


# =============================================================================
# Output Models
# =============================================================================
class ArtefactRecord(BaseModel):
    """Output model representing a stored artefact version."""
    version_uid: UUIDString = Field(..., description="UUID identifying this specific version")
    external_uid: UUIDString = Field(..., description="UUID identifying the artefact across versions")
    version: int = Field(..., description="Monotonically increasing version number")
    division: DivisionStr = Field(..., description="Division identifier")
    revoked: bool = Field(..., description="Whether this artefact version is revoked")
    format_version: int = Field(..., description="Schema format version")
    created_at: datetime = Field(..., description="Timestamp when this artefact version was created")
    artefact_hash: Multihash | None = Field(None, description="Multihash identifying artefact content")
    artefact_metadata: Any | None = Field(None, description="Optional JSON metadata for the artefact")
    artefact_type: ArtefactTypeStr | None = Field(None, description="Optional artefact type identifier")
    backlink: str | None = Field(None, description="Optional URL back to the object in the originating system")
    provenance: DIDOrUUIDList | None = Field(None, description="Optional list of provenance identifiers (normalized to UUIDs)")
    update_message: str | None = Field(None, description="Optional message describing this update")
    updated_by: str | None = Field(None, description="Optional email of the person who made this update")


@dataclass
class ProvenanceNode:
    """Represents a node in the provenance tree.

    Attributes:
        uid: The UUID identifying the artefact (version_uid if found, otherwise the original provenance uid)
        division: The division identifier of the artefact, or None if not found
        artefact_type: The type of the artefact.
        truncated: True if the node has children but recursion was stopped (due to depth or child count limits)
        children: List of child ProvenanceNodes, or None if no children or not recursed
    """
    uid: str
    division: str | None
    artefact_type: str | None
    truncated: bool = False
    children: list[ProvenanceNode] | None = field(default=None)


@dataclass
class DescendantNode:
    """Represents a descendant artefact.

    Attributes:
        uid: The version_uid of the descendant
        external_uid: The external_uid of the descendant
        division: The division identifier of the descendant
        artefact_type: The artefact type, if any
        version: The version number
        creation_date: When this version was created
    """
    uid: str
    external_uid: str
    division: str
    artefact_type: str | None
    version: int
    creation_date: datetime


@dataclass
class DescendantsResult:
    """Paginated result for descendants query.

    Attributes:
        root_uid: The UID that was queried for descendants
        descendants: List of descendant nodes for this page
        total_count: Total number of descendants across all pages
        page: Current page number (1-indexed)
        page_size: Number of items per page
        has_more: Whether there are more pages available
    """
    root_uid: str
    descendants: list[DescendantNode]
    total_count: int
    page: int
    page_size: int
    has_more: bool


@dataclass
class IssuedVCRecord:
    """Record of an issued VC stored in the database.

    Attributes:
        vc_uid: UUID identifying this VC (becomes the VC's id)
        version_uid: Reference to the DA version this VC certifies
        issuance_date: When the VC was issued
        signing_key_fragment: Which signing key was used (e.g., 'key20260216')
    """
    vc_uid: UUIDString
    version_uid: UUIDString
    issuance_date: datetime
    signing_key_fragment: str


# =============================================================================
# Database Migrations
# =============================================================================
_did_service_migrations = MigrationSet("did")


@_did_service_migrations.migration
def migration_20260212001_init(db: MongoConnector) -> None:
    """
    Initial DID service migration.

    Design notes:
    - Descendants are computed at query-time using the provenance index,
      rather than being stored in each document. This avoids document size
      growth and write amplification for high-fanout artefacts.
    - If read performance becomes a concern in the future, consider adding
      a materialized view (separate collection) that is populated
      asynchronously via background workers or change streams.
    """
    collection_name = "did_artefacts"

    # JSON Schema validator for the collection
    validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["version_uid", "external_uid", "version", "division", "format_version"],
            "properties": {
                "version_uid": {
                    "bsonType": "string",
                    "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                    "description": "UUID identifying this specific version"
                },
                "external_uid": {
                    "bsonType": "string",
                    "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                    "description": "UUID identifying the artefact across versions"
                },
                "version": {
                    "bsonType": "int",
                    "minimum": 1,
                    "description": "Monotonically increasing version number"
                },
                "artefact_hash": {
                    "bsonType": "string",
                    "description": "Hash-like string identifying artefact content"
                },
                "division": {
                    "bsonType": "string",
                    "description": "Division identifier"
                },
                "artefact_metadata": {
                    "description": "Optional JSON metadata for the artefact"
                },
                "provenance": {
                    "bsonType": "array",
                    "items": {"bsonType": "string"},
                    "description": "List of provenance identifiers (normalized to UUIDs)"
                },
                "revoked": {
                    "bsonType": "bool",
                    "description": "Whether this artefact version is revoked (defaults to false)"
                },
                "format_version": {
                    "bsonType": "int",
                    "minimum": 1,
                    "description": "Schema format version (defaults to 1)"
                },
                "created_at": {
                    "bsonType": "date",
                    "description": "Timestamp when this artefact version was created"
                }
            }
        }
    }

    # Create collection with validation
    db.db.create_collection(
        collection_name,
        validator=validator,
        validationLevel="moderate",
        validationAction="error"
    )

    collection = db.get_collection(collection_name)

    # Index on version_uid (unique identifier for each version)
    collection.create_index(
        [("version_uid", 1)],
        unique=True,
        name="idx_version_uid"
    )

    # Compound unique index on external_uid + version
    # Ensures no duplicate versions for the same external artefact
    collection.create_index(
        [("external_uid", 1), ("version", 1)],
        unique=True,
        name="idx_external_uid_version"
    )

    # Multikey index on provenance for efficient descendant queries.
    # Trade-off: Each insert pays O(k) index entries where k = provenance array length.
    # This is typically cheaper than N update operations (one per provenance item)
    # to maintain denormalized descendance arrays.
    collection.create_index(
        [("provenance", 1)],
        name="idx_provenance",
        background=True  # Non-blocking index build
    )


@_did_service_migrations.migration
def migration_20260220002_issued_vcs(db: MongoConnector) -> None:
    """
    Create the did_issued_vcs collection for tracking issued VCs.

    Design notes:
    - Each DA version can have at most one issued VC
    - VCs are stored as gzip-compressed binary blobs to save space
    - Tracking issuance_date and signing_key_fragment enables deterministic regeneration
    """
    collection_name = "did_issued_vcs"

    # JSON Schema validator for the collection
    validator = {
        "$jsonSchema": {
            "bsonType": "object",
            "required": ["vc_uid", "version_uid", "issuance_date", "signing_key_fragment", "vc_blob"],
            "properties": {
                "vc_uid": {
                    "bsonType": "string",
                    "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                    "description": "UUID identifying this VC (becomes the VC's id)"
                },
                "version_uid": {
                    "bsonType": "string",
                    "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                    "description": "Reference to the DA version this VC certifies"
                },
                "issuance_date": {
                    "bsonType": "date",
                    "description": "When the VC was issued"
                },
                "signing_key_fragment": {
                    "bsonType": "string",
                    "description": "Which signing key was used (e.g., 'key20260216')"
                },
                "vc_blob": {
                    "bsonType": "binData",
                    "description": "Gzip-compressed signed VC"
                }
            }
        }
    }

    # Create collection with validation
    db.db.create_collection(
        collection_name,
        validator=validator,
        validationLevel="moderate",
        validationAction="error"
    )

    collection = db.get_collection(collection_name)

    # Index on vc_uid (unique identifier for each VC)
    collection.create_index(
        [("vc_uid", 1)],
        unique=True,
        name="idx_vc_uid"
    )

    # Index on version_uid (unique - one VC per DA version)
    # This is the primary lookup key for finding VCs by DA version
    collection.create_index(
        [("version_uid", 1)],
        unique=True,
        name="idx_version_uid"
    )


@_did_service_migrations.migration
def migration_20260225003_artefact_type_backlink(db: MongoConnector) -> None:
    """
    Add artefact_type and backlink fields to did_artefacts collection.

    Design notes:
    - artefact_type: Optional string with pattern validation (lowercase alphanumeric + _-:/)
    - backlink: Optional string (URL back to originating system)
    - Both fields are optional and stored as metadata
    - artefact_type is included in VCs, backlink is not
    """
    collection_name = "did_artefacts"
    db.get_collection(collection_name)

    # Update validator to add new optional fields
    # Note: We use collMod to update the existing validator
    db.db.command({
        "collMod": collection_name,
        "validator": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["version_uid", "external_uid", "version", "division", "format_version"],
                "properties": {
                    "version_uid": {
                        "bsonType": "string",
                        "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                        "description": "UUID identifying this specific version"
                    },
                    "external_uid": {
                        "bsonType": "string",
                        "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                        "description": "UUID identifying the artefact across versions"
                    },
                    "version": {
                        "bsonType": "int",
                        "minimum": 1,
                        "description": "Monotonically increasing version number"
                    },
                    "artefact_hash": {
                        "bsonType": "string",
                        "description": "Hash-like string identifying artefact content"
                    },
                    "division": {
                        "bsonType": "string",
                        "description": "Division identifier"
                    },
                    "artefact_metadata": {
                        "description": "Optional JSON metadata for the artefact"
                    },
                    "artefact_type": {
                        "bsonType": "string",
                        "pattern": "^[a-z][a-z0-9_:/-]*$",
                        "description": "Optional artefact type identifier (lowercase alphanumeric + _-:/)"
                    },
                    "backlink": {
                        "bsonType": "string",
                        "description": "Optional URL back to the object in the originating system"
                    },
                    "provenance": {
                        "bsonType": "array",
                        "items": {"bsonType": "string"},
                        "description": "List of provenance identifiers (normalized to UUIDs)"
                    },
                    "revoked": {
                        "bsonType": "bool",
                        "description": "Whether this artefact version is revoked (defaults to false)"
                    },
                    "format_version": {
                        "bsonType": "int",
                        "minimum": 1,
                        "description": "Schema format version (defaults to 1)"
                    },
                    "created_at": {
                        "bsonType": "date",
                        "description": "Timestamp when this artefact version was created"
                    }
                }
            }
        },
        "validationLevel": "moderate",
        "validationAction": "error"
    })


@_did_service_migrations.migration
def migration_20260303004_update_message_fields(db: MongoConnector) -> None:
    """
    Add update_message and updated_by fields to did_artefacts collection.

    Design notes:
    - update_message: Optional string describing the update
    - updated_by: Optional string (email of the person who made the update)
    - Both fields are completely optional with no validation at database level
    """
    collection_name = "did_artefacts"
    db.get_collection(collection_name)

    # Update validator to add new optional fields
    db.db.command({
        "collMod": collection_name,
        "validator": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["version_uid", "external_uid", "version", "division", "format_version"],
                "properties": {
                    "version_uid": {
                        "bsonType": "string",
                        "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                        "description": "UUID identifying this specific version"
                    },
                    "external_uid": {
                        "bsonType": "string",
                        "pattern": "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
                        "description": "UUID identifying the artefact across versions"
                    },
                    "version": {
                        "bsonType": "int",
                        "minimum": 1,
                        "description": "Monotonically increasing version number"
                    },
                    "artefact_hash": {
                        "bsonType": "string",
                        "description": "Hash-like string identifying artefact content"
                    },
                    "division": {
                        "bsonType": "string",
                        "description": "Division identifier"
                    },
                    "artefact_metadata": {
                        "description": "Optional JSON metadata for the artefact"
                    },
                    "artefact_type": {
                        "bsonType": "string",
                        "pattern": "^[a-z][a-z0-9_:/-]*$",
                        "description": "Optional artefact type identifier (lowercase alphanumeric + _-:/)"
                    },
                    "backlink": {
                        "bsonType": "string",
                        "description": "Optional URL back to the object in the originating system"
                    },
                    "provenance": {
                        "bsonType": "array",
                        "items": {"bsonType": "string"},
                        "description": "List of provenance identifiers (normalized to UUIDs)"
                    },
                    "revoked": {
                        "bsonType": "bool",
                        "description": "Whether this artefact version is revoked (defaults to false)"
                    },
                    "format_version": {
                        "bsonType": "int",
                        "minimum": 1,
                        "description": "Schema format version (defaults to 1)"
                    },
                    "created_at": {
                        "bsonType": "date",
                        "description": "Timestamp when this artefact version was created"
                    },
                    "update_message": {
                        "bsonType": "string",
                        "description": "Optional message describing this update"
                    },
                    "updated_by": {
                        "bsonType": "string",
                        "description": "Optional email of the person who made this update"
                    }
                }
            }
        },
        "validationLevel": "moderate",
        "validationAction": "error"
    })


# =============================================================================
# Utils/helpers
# =============================================================================
def artefact_has_changes(
    existing: dict[str, Any],
    new_hash: str | None,
    new_metadata: Any | None,
    new_provenance: list[str] | None,
    new_artefact_type: str | None,
) -> bool:
    """Check if the new artefact data differs from the existing version.

    Compares artefact_hash, artefact_metadata (deep), provenance list, and artefact_type
    to determine if at least one field has changed.

    Args:
        existing: The existing artefact document from the database
        new_hash: The new artefact_hash value (or None)
        new_metadata: The new artefact_metadata value (or None)
        new_provenance: The new provenance list (or None)
        new_artefact_type: The new artefact_type value (or None)

    Returns:
        True if at least one field has changed, False otherwise
    """
    # Compare artefact_hash
    existing_hash = existing.get("artefact_hash")
    if existing_hash != new_hash:
        return True

    # Compare artefact_metadata (deep comparison)
    existing_metadata = existing.get("artefact_metadata")
    if not deep_equals(existing_metadata, new_metadata):
        return True

    # Compare provenance list
    existing_provenance = existing.get("provenance")
    # Normalize None to empty list for comparison, since both represent "no provenance"
    existing_prov_list = existing_provenance if existing_provenance is not None else []
    new_prov_list = new_provenance if new_provenance is not None else []

    if existing_prov_list != new_prov_list:
        return True

    # Compare artefact_type
    existing_artefact_type = existing.get("artefact_type")
    return existing_artefact_type != new_artefact_type


def _artefact_to_da_vc_input(artefact : dict[str, Any]) -> DigitalArtefactVCInput:
    return DigitalArtefactVCInput(
            uid=artefact["external_uid"],
            version=artefact["version"],
            version_uid=artefact["version_uid"],
            hash=artefact.get("artefact_hash"),
            metadata=artefact.get("artefact_metadata"),
            created_at=artefact["created_at"],
            division=artefact["division"],
            provenance=artefact.get("provenance"),
            artefact_type=artefact.get("artefact_type"),
            update_message=artefact.get("update_message"),
            updated_by=artefact.get("updated_by"),
        )


def compress_vc(vc: dict) -> bytes:
    """Compress a VC dictionary to gzip bytes for storage.

    Preserves the original field ordering of the VC.

    Args:
        vc: The VC dictionary to compress

    Returns:
        Gzip-compressed bytes
    """
    json_str = json.dumps(vc, separators=(',', ':'))
    return gzip.compress(json_str.encode('utf-8'))


def _vc_to_canonical_bytes(vc: dict) -> bytes:
    """Convert VC to deterministic canonical bytes for comparison.

    Uses sorted keys to ensure the same VC always produces the same bytes,
    regardless of field ordering. This is used for VC comparison/verification
    but NOT for storage (to preserve original field order).

    Args:
        vc: The VC dictionary to canonicalize

    Returns:
        Canonical bytes representation
    """
    json_str = json.dumps(vc, sort_keys=True, separators=(',', ':'))
    return json_str.encode('utf-8')


def decompress_vc(blob: bytes) -> dict:
    """Decompress gzip bytes to a VC dictionary.

    Args:
        blob: Gzip-compressed bytes

    Returns:
        The decompressed VC dictionary

    Raises:
        ValueError: If decompression or JSON parsing fails
    """
    try:
        json_str = gzip.decompress(blob).decode('utf-8')
        return json.loads(json_str)
    except (gzip.BadGzipFile, json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"Failed to decompress VC blob: {e}") from e


# =============================================================================
# DIDService definition
# =============================================================================
class DIDService:
    """Service provider for DID-related actions.

    This service handles all DID-related operations including:
    - Artefact management (create, update, query)
    - Division key management
    - Verifiable Credential generation

    The service supports dependency injection for both database and vault,
    enabling easy testing with mocks.

    Example usage:
        # Production - use get_did_service() from dependencies
        from app.routers.dependencies import get_did_service
        did_svc = get_did_service()

        # Testing with mocks
        mock_client = InMemoryVaultClient()
        vault_svc = VaultService(mock_client, "secret")
        db = MongoConnector.from_client(mongomock.MongoClient(), "test_db")
        did_svc = DIDService(db=db, vault_svc=vault_svc, run_migrations=True)
    """

    _artefacts_col_name = "did_artefacts"  # Collection name for artefacts
    _issued_vcs_col_name = "did_issued_vcs"  # Collection name for issued VCs

    db: MongoConnector
    _vault_svc: VaultService

    # List of divisions that must have signing keys provisioned. Currently
    # hardcoded, in the future we will have a management API endpoint to create
    # these.
    _required_divisions: ClassVar[list[str]] = ["advisory", "epdw", "demodivision"]

    @classmethod
    def ensure_collections_for_testing(cls, db: MongoConnector) -> None:
        """Create collections with indexes but without validators for testing.

        This method is intended for test environments using mongomock, which doesn't
        support MongoDB collection validators. It creates the same indexes as the
        migrations but skips validator creation.

        For production environments, use migrations (run_migrations=True) instead.

        This is the single source of truth for test collection schema. Any changes
        to collection indexes should be reflected both in migrations AND here.

        Args:
            db: MongoConnector instance
        """
        # did_artefacts collection with indexes
        artefacts = db.get_collection(cls._artefacts_col_name)
        artefacts.create_index([("version_uid", 1)], unique=True, name="idx_version_uid")
        artefacts.create_index(
            [("external_uid", 1), ("version", 1)],
            unique=True,
            name="idx_external_uid_version"
        )
        artefacts.create_index([("provenance", 1)], name="idx_provenance")

        # did_issued_vcs collection with indexes
        vcs = db.get_collection(cls._issued_vcs_col_name)
        vcs.create_index([("vc_uid", 1)], unique=True, name="idx_vc_uid")
        vcs.create_index([("version_uid", 1)], unique=True, name="idx_version_uid")

    def __init__(
        self,
        db: MongoConnector,
        vault_svc: VaultService,
        run_migrations: bool = True,
        ensure_signing_keys: bool = True,
    ):
        """Initialize DIDService with injected dependencies.

        Args:
            db: MongoConnector instance for database operations
            vault_svc: VaultService instance for vault operations
            run_migrations: Whether to run database migrations on init (default True)
            ensure_signing_keys: Whether to ensure division signing keys exist (default True)
        """
        self.db = db
        self._vault_svc = vault_svc

        if run_migrations:
            self.db.run_migrations(_did_service_migrations)

        # Ensure required divisions have at least one signing key in vault
        if ensure_signing_keys:
            for division in self._required_divisions:
                self._vault_svc.ensure_division_signing_key(division)


    def _validate_id_list_exists(
        self, id_list: DIDOrUUIDList, collection
    ) -> None:
        """
        Validate that all identifiers in the list exist in did_artefacts. This
        is the internal version of _validate_id_list_exists.

        Args:
            id_list: List of canonicalized UUID strings
            collection: The did_artefacts collection

        Raises:
            ProvenanceNotFoundError: If an identifier doesn't exist
        """
        for uuid_str in id_list:
            # Check if this UUID exists as version_uid or external_uid in did_artefacts
            exists = collection.find_one({
                "$or": [
                    {"version_uid": uuid_str},
                    {"external_uid": uuid_str}
                ]
            })
            if not exists:
                raise ProvenanceNotFoundError(uuid_str)

    def validate_id_list_exists(self, id_list: DIDOrUUIDList) -> None:
        """
        Validate that all identifiers in the list exist in did_artefacts.

        Args:
            id_list: List of canonicalized UUID strings

        Raises:
            ProvenanceNotFoundError: If an identifier doesn't exist
        """
        collection = self.db.get_collection(self._artefacts_col_name)
        self._validate_id_list_exists(id_list, collection)

    def validate_ids_may_exist_division(self, id_list: DIDOrUUIDList, division: DivisionStr):
        """
        Validates whether the given set of ids exist in a given division. It is
        ok if the given artefact id does not exist, but if the artefact does
        exist, then it MUST be in the given division, otherwise this raises an
        exception.

        Args:
            id_list: List of canonicalized UUID strings
            division: The target division

        Raises:
            DivisionMismatchError: If an artefact is in the wrong division.
        """
        collection = self.db.get_collection(self._artefacts_col_name)
        for uuid_str in id_list:
            # Check if this UUID exists as version_uid or external_uid in did_artefacts
            exists = collection.find_one({
                "$or": [
                    {"version_uid": uuid_str},
                    {"external_uid": uuid_str}
                ]
            })
            if not exists:
                continue
            if exists["division"] != division:
                raise DivisionMismatchError(uuid_str, exists["division"], division)


    def _find_artefact_by_uid(self, uid: CanonicalizedUUID, collection) -> dict | None:
        """
        Find an artefact by version_uid or external_uid.

        If the uid matches a version_uid, returns that specific version.
        If it matches an external_uid, returns the latest version.

        Args:
            uid: The canonicalized UUID to search for (version_uid or external_uid)
            collection: The did_artefacts collection

        Returns:
            The matching document, or None if not found
        """
        # First try to find by version_uid (exact version match)
        doc = collection.find_one({"version_uid": uid})
        if doc is not None:
            return doc

        # Try finding by external_uid and get latest version
        return collection.find_one(
            {"external_uid": uid},
            sort=[("version", -1)]
        )

    def upsert_artefact(self, artefact: ArtefactInput) -> ArtefactRecord:
        """
        Upsert an artefact by creating a new version. If the artefact does not
        exist, it will be created with version 1.

        Args:
            artefact: The artefact input data

        Returns:
            ArtefactRecord: The inserted artefact record

        Raises:
            DivisionMismatchError: If division doesn't match existing artefact's division
            ArtefactNoChangesError: If no changes detected in artefact_hash,
                artefact_metadata, or provenance compared to latest version
            VersionConflictError: If a concurrent update causes a version conflict
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        # Find the latest version for this external_uid
        latest_doc = collection.find_one(
            {"external_uid": artefact.external_uid},
            sort=[("version", -1)]
        )

        if latest_doc is not None:
            # Validate division matches
            if latest_doc["division"] != artefact.division:
                raise DivisionMismatchError(
                    external_uid=artefact.external_uid,
                    existing_division=latest_doc["division"],
                    target_division=artefact.division,
                )

            # Validate at least one thing changed (either artefact_hash,
            # artefact_metadata (deep), provenance list, or artefact_type).
            if not artefact_has_changes(
                existing=latest_doc,
                new_hash=artefact.artefact_hash,
                new_metadata=artefact.artefact_metadata,
                new_provenance=list(artefact.provenance) if artefact.provenance else None,
                new_artefact_type=artefact.artefact_type,
            ):
                raise ArtefactNoChangesError(external_uid=artefact.external_uid)

            new_version = latest_doc["version"] + 1
        else:
            # First version
            new_version = 1

        # Validate provenance items exist (already canonicalized by DIDOrUUIDList type)
        if artefact.provenance is not None:
            self._validate_id_list_exists(artefact.provenance, collection)

        # Generate new version_uid
        new_version_uid = str(self.db.random_uuid())

        # Determine created_at timestamp
        created_at = artefact.created_at if artefact.created_at is not None else self.db.now()

        # Build the document to insert
        new_doc = {
            "version_uid": new_version_uid,
            "external_uid": artefact.external_uid,
            "version": new_version,
            "division": artefact.division,
            "revoked": False,  # Revocation will be done by a different method
            "format_version": _default_format_version,  # Always use latest format_version
            "created_at": created_at,
        }

        # Add optional fields if provided
        if artefact.artefact_hash is not None:
            new_doc["artefact_hash"] = artefact.artefact_hash
        if artefact.artefact_metadata is not None:
            new_doc["artefact_metadata"] = artefact.artefact_metadata
        if artefact.artefact_type is not None:
            new_doc["artefact_type"] = artefact.artefact_type
        if artefact.backlink is not None:
            new_doc["backlink"] = artefact.backlink
        if artefact.provenance is not None and len(artefact.provenance) > 0:
            new_doc["provenance"] = artefact.provenance
        if artefact.update_message is not None:
            new_doc["update_message"] = artefact.update_message
        if artefact.updated_by is not None:
            new_doc["updated_by"] = artefact.updated_by

        # Insert the new version, handling potential concurrent update conflicts
        try:
            collection.insert_one(new_doc)
        except DuplicateKeyError as e:
            # Check if conflict is on the external_uid + version unique index
            if "idx_external_uid_version" in str(e):
                raise VersionConflictError(
                    external_uid=artefact.external_uid,
                    version=new_version,
                ) from e
            raise

        # Log DA creation or new version
        if new_version == 1:
            logger.info(
                "Created new DA: external_uid=%s, version=%d, version_uid=%s, division=%s",
                artefact.external_uid,
                new_version,
                new_version_uid,
                artefact.division,
            )
        else:
            logger.info(
                "Added new version to DA: external_uid=%s, version=%d, version_uid=%s, division=%s",
                artefact.external_uid,
                new_version,
                new_version_uid,
                artefact.division,
            )

        # Return the ArtefactRecord (exclude MongoDB's _id)
        del new_doc["_id"]
        return ArtefactRecord(**new_doc)

    def get_descendants(self, uid: CanonicalizedUUID) -> list[dict]:
        """
        Get all artefacts that reference the given uid in their provenance.

        This performs a query-time computation using the provenance index,
        avoiding the need to store descendance in the document itself.

        Args:
            uid: The canonicalized UUID to find descendants of (version_uid or external_uid)

        Returns:
            List of artefact documents that have this uid in their provenance
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        # Find the artefact to get both version_uid and external_uid
        artefact = self._find_artefact_by_uid(uid, collection)
        if artefact is None:
            return []

        # Query for documents that reference either the version_uid or external_uid
        # in their provenance array
        uids_to_search = [artefact["version_uid"], artefact["external_uid"]]
        cursor = collection.find({
            "provenance": {"$in": uids_to_search}
        })

        return list(cursor)

    def get_descendants_paginated(
        self,
        uid: CanonicalizedUUID,
        page: int = 1,
        page_size: int = 20,
    ) -> DescendantsResult:
        """
        Get paginated descendants of an artefact.

        Returns only the latest version of each descendant artefact,
        sorted by creation date (newest first).

        Args:
            uid: The canonicalized UUID to find descendants of (version_uid or external_uid)
            page: Page number (1-indexed)
            page_size: Number of items per page (max 100)

        Returns:
            DescendantsResult with paginated descendants and metadata

        Raises:
            ArtefactNotFoundError: If the root artefact is not found
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        # Find the artefact to get both version_uid and external_uid
        artefact = self._find_artefact_by_uid(uid, collection)
        if artefact is None:
            raise ArtefactNotFoundError(uid=uid, division=None)

        # Query for documents that reference either the version_uid or external_uid
        # in their provenance array
        uids_to_search = [artefact["version_uid"], artefact["external_uid"]]

        # Use aggregation to get only the latest version of each descendant
        # and paginate the results
        pipeline = [
            # Match documents that have this uid in provenance
            {"$match": {"provenance": {"$in": uids_to_search}}},
            # Sort by external_uid and version (for grouping)
            {"$sort": {"external_uid": 1, "version": -1}},
            # Group by external_uid and take the first (latest version)
            {
                "$group": {
                    "_id": "$external_uid",
                    "doc": {"$first": "$$ROOT"}
                }
            },
            # Replace root with the document
            {"$replaceRoot": {"newRoot": "$doc"}},
            # Sort by creation date (newest first)
            {"$sort": {"created_at": -1}},
            # Add pagination metadata using $facet
            {
                "$facet": {
                    "metadata": [{"$count": "total"}],
                    "data": [
                        {"$skip": (page - 1) * page_size},
                        {"$limit": page_size}
                    ]
                }
            }
        ]

        result = list(collection.aggregate(pipeline))

        # Extract results from facet
        if not result:
            total_count = 0
            descendants_docs = []
        else:
            metadata = result[0]["metadata"]
            total_count = metadata[0]["total"] if metadata else 0
            descendants_docs = result[0]["data"]

        # Convert to DescendantNode objects
        descendants = []
        for doc in descendants_docs:
            descendants.append(DescendantNode(
                uid=doc["version_uid"],
                external_uid=doc["external_uid"],
                division=doc["division"],
                artefact_type=doc.get("artefact_type"),
                version=doc["version"],
                creation_date=doc["created_at"],
            ))

        # Calculate has_more
        has_more = (page * page_size) < total_count

        return DescendantsResult(
            root_uid=uid,
            descendants=descendants,
            total_count=total_count,
            page=page,
            page_size=page_size,
            has_more=has_more,
        )

    def find_by_external_uid(
        self, external_uid: UUIDString, division: DivisionStr | None = None
    ) -> ArtefactRecord | None:
        """
        Find the latest version of an artefact by external_uid.

        Args:
            external_uid: The external UUID of the artefact
            division: Optional division identifier. If specified, the artefact
                      must match that division. If None, any division is acceptable.

        Returns:
            ArtefactRecord if found, None otherwise

        Raises:
            DivisionMismatchError: If the artefact is in the wrong division.
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        query: dict[str, Any] = {"external_uid": external_uid}
        doc = collection.find_one(query, sort=[("version", -1)])
        if doc is None:
            return None

        # Double check division.
        if division is not None and doc["division"] != division:
            raise DivisionMismatchError(external_uid, doc["division"], division)

        # Remove MongoDB _id before returning
        doc.pop("_id", None)
        return ArtefactRecord(**doc)

    def find_artefact_by_uid_and_type(
        self, uid: CanonicalizedUUID, division: DivisionStr, artefact_type: ArtefactTypeStr
    ) -> ArtefactRecord | None:
        """
        Find an artefact by uid (version_uid or external_uid) and validate its type and division.

        If the uid matches a version_uid, returns that specific version.
        If it matches an external_uid, returns the latest version.
        The artefact must match both the specified division and artefact_type.

        Args:
            uid: The canonicalized UUID to search for (version_uid or external_uid)
            division: The division the artefact must belong to
            artefact_type: The artefact type the artefact must have

        Returns:
            ArtefactRecord if found and matches division/type, None otherwise
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        # First try to find by version_uid (exact version match)
        doc = collection.find_one({
            "version_uid": uid,
            "division": division,
            "artefact_type": artefact_type
        })
        if doc is not None:
            doc.pop("_id", None)
            return ArtefactRecord(**doc)

        # Try finding by external_uid and get latest version
        doc = collection.find_one(
            {
                "external_uid": uid,
                "division": division,
                "artefact_type": artefact_type
            },
            sort=[("version", -1)]
        )
        if doc is None:
            return None
        doc.pop("_id", None)
        return ArtefactRecord(**doc)

    def find_by_provenance(
        self, provenance_uid: UUIDString, division: DivisionStr | None = None
    ) -> list[ArtefactRecord]:
        """
        Find all artefacts that have the given uid in their provenance.
        Returns only the latest version of each artefact.

        Args:
            provenance_uid: The UUID that should be in the provenance array
            division: Optional division identifier. If specified, only artefacts
                      in that division are returned. If None, all divisions.

        Returns:
            List of ArtefactRecords that have this provenance
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        # Build match criteria
        match_criteria: dict[str, Any] = {"provenance": provenance_uid}
        if division is not None:
            match_criteria["division"] = division

        # Use aggregation to get only the latest version of each external_uid
        pipeline = [
            {"$match": match_criteria},
            {"$sort": {"external_uid": 1, "version": -1}},
            {
                "$group": {
                    "_id": "$external_uid",
                    "doc": {"$first": "$$ROOT"}
                }
            },
            {"$replaceRoot": {"newRoot": "$doc"}}
        ]

        results = []
        for doc in collection.aggregate(pipeline):
            doc.pop("_id", None)
            results.append(ArtefactRecord(**doc))
        return results

    def _fetch_division_pub_keys(self, division: DivisionStr) -> list[dict]:
        """Fetch the public keys for a division from vault.

        Retrieves public key information from vault at path:
        divisions/{division}/public_keys

        Args:
            division: The division identifier.

        Returns:
            List of key information dictionaries, each containing:
                - fragment: The key fragment identifier
                - public_key_multibase: The public key in multibase format

        Raises:
            DivisionKeysNotFound: If no keys are found registered for the division.
        """
        try:
            return self._vault_svc.get_division_public_keys(division)
        except DivisionPublicKeysNotFoundError as e:
            raise DivisionKeysNotFoundError(division=division) from e

    def _get_active_signing_key_fragment(self, division: DivisionStr) -> str:
        """Get the fragment identifier of the active (latest) signing key.

        The active key is determined by sorting available fragments
        alphabetically and returning the last one (latest by convention).

        Args:
            division: The division identifier.

        Returns:
            The fragment identifier of the active signing key.

        Raises:
            DivisionKeysNotFound: If no signing keys exist for the division.
        """
        try:
            return self._vault_svc.get_active_signing_key_fragment(division)
        except SigningKeyNotFoundError as e:
            raise DivisionKeysNotFoundError(division=division) from e

    def division_did_doc(self, division: str) -> dict:
        """Generates the DID document in JSON-LD format for a given division.

        The division should've been previously recorded in the database.

        Args:
            division: The division identifier.

        Returns:
            The DID document as a dictionary.
        """
        assertion_keys = self._fetch_division_pub_keys(division)
        did_id = division_did_from_division(division)

        verification_methods = []
        assertion_method_refs = []

        for key_info in assertion_keys:
            key_id = f"{did_id}#{key_info['fragment']}"
            verification_methods.append({
                "id": key_id,
                "type": "Multikey",
                "controller": did_id,
                "publicKeyMultibase": key_info["public_key_multibase"],
            })
            assertion_method_refs.append(key_id)

        return {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/multikey/v1",
            ],
            "id": did_id,
            "verificationMethod": verification_methods,
            "assertionMethod": assertion_method_refs,
            # "authentication": assertion_method_refs,  # Same keys used for VP signing
        }

    def get_artefact_overview(
        self, uid: CanonicalizedUUID
    ) -> tuple[dict, dict | None]:
        """
        Get overview information for an artefact.

        Returns the artefact document and, if a newer version exists,
        the latest version document.

        Args:
            uid: The canonicalized UUID to search for (version_uid or external_uid)

        Returns:
            A tuple of (artefact_doc, latest_version_doc).
            latest_version_doc is None if the found artefact is already the latest version.

        Raises:
            ArtefactNotFoundError: If the artefact is not found.
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        # Find the artefact by uid
        artefact = self._find_artefact_by_uid(uid, collection)
        if artefact is None:
            raise ArtefactNotFoundError(uid=uid, division=None)

        # Check if there's a newer version by querying for the latest version
        # with the same external_uid
        latest_doc = collection.find_one(
            {"external_uid": artefact["external_uid"]},
            sort=[("version", -1)]
        )

        # If latest_doc has a higher version, return it as latest_version
        latest_version = None
        if latest_doc and latest_doc["version"] > artefact["version"]:
            latest_version = latest_doc

        return artefact, latest_version

    def get_all_versions(self, uid: CanonicalizedUUID) -> list[dict]:
        """
        Get all versions of an artefact.

        Args:
            uid: The canonicalized UUID to search for (version_uid or external_uid)

        Returns:
            List of version documents sorted by version number (ascending).
            Each document contains: external_uid, version, version_uid, created_at, revoked.

        Raises:
            ArtefactNotFoundError: If the artefact is not found.
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        # Find the artefact by uid to get the external_uid
        artefact = self._find_artefact_by_uid(uid, collection)
        if artefact is None:
            raise ArtefactNotFoundError(uid=uid, division=None)

        # Query all versions by external_uid, sorted by version (ascending)
        cursor = collection.find(
            {"external_uid": artefact["external_uid"]},
            {"external_uid": 1, "version": 1, "version_uid": 1, "created_at": 1, "revoked": 1, "_id": 0}
        ).sort("version", 1)

        return list(cursor)

    def get_provenance_tree(
        self,
        uid: CanonicalizedUUID,
        max_depth: int = 3,
        max_children: int = 10,
    ) -> list[ProvenanceNode]:
        """
        Get the recursive provenance tree for an artefact.

        Traverses the provenance graph up to max_depth levels deep.
        If a node has more than max_children provenance items, it won't be
        recursed into (marked as truncated).

        Args:
            uid: The canonicalized UUID to get provenance for
            max_depth: Maximum depth to recurse (default 3)
            max_children: Maximum children count before truncating recursion (default 10)

        Returns:
            A list of ProvenanceNode objects representing the provenance tree.

        Raises:
            ArtefactNotFoundError: If the root artefact is not found.
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        # Find the root artefact
        root_artefact = self._find_artefact_by_uid(uid, collection)
        if root_artefact is None:
            raise ArtefactNotFoundError(uid=uid, division=None)

        # Get the direct provenance of the root
        root_provenance = root_artefact.get("provenance") or []

        # Build the tree recursively
        return self._build_provenance_tree(
            collection=collection,
            provenance_uids=root_provenance,
            current_depth=1,
            max_depth=max_depth,
            max_children=max_children,
        )

    def _build_provenance_tree(
        self,
        collection,
        provenance_uids: list[str],
        current_depth: int,
        max_depth: int,
        max_children: int,
    ) -> list[ProvenanceNode]:
        """
        Recursively build the provenance tree.

        Args:
            collection: The MongoDB collection
            provenance_uids: List of UIDs to process at this level
            current_depth: Current depth in the tree (1-indexed)
            max_depth: Maximum depth to recurse
            max_children: Maximum children count before truncating

        Returns:
            List of ProvenanceNode objects
        """
        nodes: list[ProvenanceNode] = []

        for prov_uid in provenance_uids:
            # Try to find this provenance artefact
            artefact = self._find_artefact_by_uid(prov_uid, collection)

            if artefact is None:
                # Artefact not found - include it with minimal info
                nodes.append(ProvenanceNode(
                    uid=prov_uid,
                    division=None,
                    artefact_type=None,
                    truncated=False,
                    children=None,
                ))
                continue

            # Get this artefact's provenance
            child_provenance = artefact.get("provenance") or []
            has_children = len(child_provenance) > 0

            # Determine if we should recurse
            should_recurse = (
                has_children
                and current_depth < max_depth
                and len(child_provenance) <= max_children
            )

            if should_recurse:
                # Recurse into children
                children = self._build_provenance_tree(
                    collection=collection,
                    provenance_uids=child_provenance,
                    current_depth=current_depth + 1,
                    max_depth=max_depth,
                    max_children=max_children,
                )
                nodes.append(ProvenanceNode(
                    uid=artefact["version_uid"],
                    division=artefact.get("division"),
                    artefact_type=artefact.get("artefact_type"),
                    truncated=False,
                    children=children if children else None,
                ))
            else:
                # Don't recurse - mark as truncated if it has children
                nodes.append(ProvenanceNode(
                    uid=artefact["version_uid"],
                    division=artefact.get("division"),
                    artefact_type=artefact.get("artefact_type"),
                    truncated=has_children,
                    children=None,
                ))

        return nodes

    def find_issued_vc(self, version_uid: UUIDString) -> IssuedVCRecord | None:
        """Find an existing issued VC for a DA version.

        Args:
            version_uid: The version_uid of the DA to look up

        Returns:
            IssuedVCRecord if found, None otherwise
        """
        from datetime import timezone

        collection = self.db.get_collection(self._issued_vcs_col_name)
        doc = collection.find_one({"version_uid": version_uid})

        if doc is None:
            return None

        # Remove MongoDB _id before returning
        doc.pop("_id", None)

        # MongoDB may strip timezone info - add it back if missing
        issuance_date = doc["issuance_date"]
        if issuance_date.tzinfo is None:
            issuance_date = issuance_date.replace(tzinfo=timezone.utc)

        return IssuedVCRecord(
            vc_uid=doc["vc_uid"],
            version_uid=doc["version_uid"],
            issuance_date=issuance_date,
            signing_key_fragment=doc["signing_key_fragment"],
        )

    def get_issued_vc(self, version_uid: UUIDString) -> dict:
        """Get the stored VC document for a DA version.

        Returns the decompressed VC from storage.

        Args:
            version_uid: The version_uid of the DA

        Returns:
            The decompressed VC document

        Raises:
            VCNotFoundError: If no VC exists for this version_uid
        """
        from app.services.exceptions import VCNotFoundError

        collection = self.db.get_collection(self._issued_vcs_col_name)
        doc = collection.find_one({"version_uid": version_uid})

        if doc is None:
            raise VCNotFoundError(version_uid)

        # Decompress and return the VC
        return decompress_vc(doc["vc_blob"])

    def _store_issued_vc(
        self,
        vc_uid: UUIDString,
        version_uid: UUIDString,
        issuance_date: datetime,
        signing_key_fragment: str,
        vc: dict,
    ) -> IssuedVCRecord:
        """Store an issued VC in the database.

        Args:
            vc_uid: UUID for the VC itself
            version_uid: The DA version this VC certifies
            issuance_date: When the VC was issued
            signing_key_fragment: Which key was used to sign
            vc: The signed VC document

        Returns:
            IssuedVCRecord with the stored metadata

        Raises:
            VCAlreadyExistsError: If a VC already exists for this version_uid
        """
        from app.services.exceptions import VCAlreadyExistsError

        collection = self.db.get_collection(self._issued_vcs_col_name)

        # Compress the VC for storage
        vc_blob = compress_vc(vc)

        doc = {
            "vc_uid": vc_uid,
            "version_uid": version_uid,
            "issuance_date": issuance_date,
            "signing_key_fragment": signing_key_fragment,
            "vc_blob": vc_blob,
        }

        try:
            collection.insert_one(doc)
        except DuplicateKeyError as e:
            # A VC already exists for this version_uid
            raise VCAlreadyExistsError(version_uid) from e

        return IssuedVCRecord(
            vc_uid=vc_uid,
            version_uid=version_uid,
            issuance_date=issuance_date,
            signing_key_fragment=signing_key_fragment,
        )

    def _generate_vc_internal(
        self,
        artefact: dict,
        vc_uid: UUIDString,
        issuance_date: datetime,
        signing_key_fragment: str,
    ) -> dict:
        """Generate a signed VC deterministically given all inputs.

        This is the core generation function that produces the same VC
        given the same inputs. It's used both for initial VC generation
        and for deterministic regeneration.

        Args:
            artefact: The artefact document from database
            vc_uid: The UUID for the VC's id field
            issuance_date: When the VC is/was issued
            signing_key_fragment: Which signing key to use

        Returns:
            The signed VC document

        Raises:
            SigningKeyNotAvailableError: If the signing key is not found
            HTTPException: If signing fails
        """
        from app.services.exceptions import SigningKeyNotAvailableError

        division = division_from_str(artefact["division"])
        division_did = division_did_from_division(division)

        # Create the unsigned VC with the provided vc_id
        unsigned_vc = generate_digital_artefact_vc(
            format=artefact["format_version"],
            da=_artefact_to_da_vc_input(artefact),
            issuance_date=issuance_date,
            vc_id=vc_uid,
        )

        # Fetch and use the specific signing key
        try:
            with self._vault_svc.signing_key_context(division, signing_key_fragment) as (signing_key, frag):
                verification_method = f"{division_did}#{frag}"

                return sign_vc(
                    vc=unsigned_vc,
                    secret_key=signing_key,
                    verification_method=verification_method,
                    created=issuance_date,
                )
        except SigningKeyNotFoundError as e:
            raise SigningKeyNotAvailableError(division=division, fragment=signing_key_fragment) from e
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to sign VC for DA {artefact['version_uid']} version {artefact['version']} division {division}: {e}",
            ) from e

    def issue_artefact_vc(
        self,
        division: DivisionStr | None,
        uid: UUIDString,
        force_regenerate: bool = False,
    ) -> dict:
        """Issue or retrieve a VC for a Digital Artefact.

        This method handles VC issuance with tracking and deterministic regeneration:
        1. Find the DA (resolve external_uid to latest version_uid if needed)
        2. Check if VC already exists for this version_uid
        3. If exists and not force_regenerate: return stored VC
        4. If exists and force_regenerate: regenerate and verify match
        5. If not exists: generate new VC, store it, return it

        Args:
            division: Division filter (None = any division acceptable)
            uid: The DA's version_uid or external_uid
            force_regenerate: If True, regenerate and verify against stored VC

        Returns:
            The signed VC document

        Raises:
            ArtefactNotFoundError: If the artefact is not found
            DivisionKeysNotFound: If no signing keys exist for the division
            VCRegenerationMismatchError: If force_regenerate=True and regenerated VC doesn't match
            HTTPException: If signing fails
        """
        from app.services.exceptions import VCRegenerationMismatchError

        collection = self.db.get_collection(self._artefacts_col_name)

        # Find the artefact (resolves external_uid to latest version)
        artefact = self._find_artefact_by_uid(uid, collection)

        # Validate artefact exists and division matches
        if artefact is None:
            raise ArtefactNotFoundError(uid=uid, division=division)
        if artefact["division"] is None or artefact["division"] == "":
            raise RuntimeError("artefact does not have a division")
        elif division is None:
            # Any division acceptable. Use the one in the artefact.
            division = division_from_str(artefact["division"])
        elif artefact["division"] != division:
            # MUST be ArtefactNotFoundError to avoid leaking division info
            raise ArtefactNotFoundError(uid=uid, division=division)

        version_uid = artefact["version_uid"]

        # Check if a VC already exists for this version
        existing_vc_record = self.find_issued_vc(version_uid)

        if existing_vc_record is not None:
            if force_regenerate:
                # Regenerate and verify it matches the stored VC
                regenerated_vc = self._generate_vc_internal(
                    artefact=artefact,
                    vc_uid=existing_vc_record.vc_uid,
                    issuance_date=existing_vc_record.issuance_date,
                    signing_key_fragment=existing_vc_record.signing_key_fragment,
                )

                stored_vc = self.get_issued_vc(version_uid)

                # Compare using canonical bytes (with sorted keys) to ignore field ordering
                regenerated_canonical = _vc_to_canonical_bytes(regenerated_vc)
                stored_canonical = _vc_to_canonical_bytes(stored_vc)

                if regenerated_canonical != stored_canonical:
                    raise VCRegenerationMismatchError(
                        version_uid=version_uid,
                        details="Regenerated VC does not match stored VC"
                    )

                return regenerated_vc
            else:
                # Return the stored VC
                logger.info(
                    "Fetched existing VC for DA: version_uid=%s, vc_uid=%s",
                    version_uid,
                    existing_vc_record.vc_uid,
                )
                return self.get_issued_vc(version_uid)

        # No existing VC - generate and store a new one
        vc_uid = str(self.db.random_uuid())
        # Truncate to millisecond precision to match MongoDB storage
        # MongoDB stores datetimes with millisecond precision, not microseconds
        now = self.db.now()
        issuance_date = now.replace(microsecond=now.microsecond // 1000 * 1000)

        # Get the active signing key for this division
        try:
            fragment = self._get_active_signing_key_fragment(division)
        except SigningKeyNotFoundError as e:
            raise DivisionKeysNotFoundError(division=division) from e

        # Generate the VC
        vc = self._generate_vc_internal(
            artefact=artefact,
            vc_uid=vc_uid,
            issuance_date=issuance_date,
            signing_key_fragment=fragment,
        )

        # Store the VC
        self._store_issued_vc(
            vc_uid=vc_uid,
            version_uid=version_uid,
            issuance_date=issuance_date,
            signing_key_fragment=fragment,
            vc=vc,
        )

        # Log VC generation
        logger.info(
            "Generated new VC for DA: version_uid=%s, vc_uid=%s",
            version_uid,
            vc_uid,
        )

        return vc

    def regenerate_and_verify_vc(self, version_uid: UUIDString) -> tuple[dict, bool]:
        """Regenerate a VC and verify it matches the stored version.

        Args:
            version_uid: The version_uid of the DA

        Returns:
            Tuple of (regenerated_vc, matches_stored)

        Raises:
            VCNotFoundError: If no VC exists for this version_uid
            ArtefactNotFoundError: If the DA is not found
            SigningKeyNotAvailableError: If the signing key is no longer available
        """
        from app.services.exceptions import VCNotFoundError

        # Get the issued VC record
        vc_record = self.find_issued_vc(version_uid)
        if vc_record is None:
            raise VCNotFoundError(version_uid)

        # Get the artefact
        collection = self.db.get_collection(self._artefacts_col_name)
        artefact = collection.find_one({"version_uid": version_uid})
        if artefact is None:
            raise ArtefactNotFoundError(uid=version_uid, division=None)

        # Regenerate the VC using the stored parameters
        regenerated_vc = self._generate_vc_internal(
            artefact=artefact,
            vc_uid=vc_record.vc_uid,
            issuance_date=vc_record.issuance_date,
            signing_key_fragment=vc_record.signing_key_fragment,
        )

        # Get the stored VC and compare
        stored_vc = self.get_issued_vc(version_uid)

        # Compare using canonical bytes (with sorted keys) to ignore field ordering
        regenerated_canonical = _vc_to_canonical_bytes(regenerated_vc)
        stored_canonical = _vc_to_canonical_bytes(stored_vc)
        matches = (regenerated_canonical == stored_canonical)

        return regenerated_vc, matches
