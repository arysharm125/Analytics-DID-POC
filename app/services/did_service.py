from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, AsyncGenerator, ClassVar, Optional

from fastapi import Depends
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.database import MigrationSet, MongoConnector, get_global_db
from app.routers.basetypes import (
    UUID_PATTERN,
    UUIDString,
    DIDOrUUIDList,
    DivisionStr,
    CanonicalizedUUID,
    Multihash,
)
from app.services.exceptions import (
    DivisionMismatchError,
    ProvenanceNotFoundError,
    VersionConflictError,
)


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
    artefact_hash: Optional[Multihash] = Field(default=None, description="Multihash identifying artefact content")
    artefact_metadata: Optional[Any] = Field(default=None, description="Optional JSON metadata for the artefact")
    provenance: Optional[DIDOrUUIDList] = Field(
        default=None,
        description="Optional list of provenance identifiers (UUIDs or DIDs). "
                    "Each item is validated and canonicalized to UUID format."
    )
    created_at: Optional[datetime] = Field(default=None, description="Creation timestamp")


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
    artefact_hash: Optional[Multihash] = Field(None, description="Multihash identifying artefact content")
    artefact_metadata: Optional[Any] = Field(None, description="Optional JSON metadata for the artefact")
    provenance: Optional[DIDOrUUIDList] = Field(None, description="Optional list of provenance identifiers (normalized to UUIDs)")


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
            "required": ["version_uid", "external_uid", "version", "division"],
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


# =============================================================================
# DIDService definition
# =============================================================================
class DIDService:
    """Service provider for DID-related actions."""

    """Singleton reference to DIDService instance."""
    _singleton_svc: ClassVar[Optional["DIDService"]] = None

    @classmethod
    def _get_instance(cls, db: MongoConnector) -> "DIDService":
        if cls._singleton_svc is None:
            cls._singleton_svc = cls(db)
        return cls._singleton_svc

    db: MongoConnector

    def __init__(self, db: MongoConnector):
        self.db = db
        self.db.run_migrations(_did_service_migrations)


    def _validate_id_list_exists(
        self, id_list: DIDOrUUIDList, collection
    ) -> None:
        """
        Validate that all identifiers in the list exist in did_artefacts.

        Note: The list is already canonicalized to UUIDs by the
        DIDOrUUIDList type validator.

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

    def _find_artefact_by_uid(self, uid: CanonicalizedUUID, collection) -> Optional[dict]:
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
            VersionConflictError: If a concurrent update causes a version conflict
        """
        collection = self.db.get_collection("did_artefacts")

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
                    new_division=artefact.division,
                )
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
        if artefact.provenance is not None and len(artefact.provenance) > 0:
            new_doc["provenance"] = artefact.provenance

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
        collection = self.db.get_collection("did_artefacts")

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


# =============================================================================
# FastAPI Dependency Injection
# =============================================================================

def _get_db() -> MongoConnector:
    """FastAPI dependency to get MongoConnector instance."""
    return get_global_db()


# Type alias for MongoConnector dependency injection
MongoConnectorDep = Annotated[MongoConnector, Depends(_get_db)]


def _get_DID_service(db: MongoConnectorDep) -> DIDService:
    """FastAPI dependency to get DIDService instance with injected database."""
    return DIDService._get_instance(db=db)


# Type alias for DIDService dependency injection
DIDServiceDep = Annotated[DIDService, Depends(_get_DID_service)]


@asynccontextmanager
async def did_service_lifespan() -> AsyncGenerator[None, None]:
    """Control lifespan of global DIDService instance."""
    db = get_global_db()
    DIDService._get_instance(db=db)
    try:
        yield
    finally:
        pass  # No shutdown procedure yet.
