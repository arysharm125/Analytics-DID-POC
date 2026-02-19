from __future__ import annotations
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, AsyncGenerator, ClassVar, Optional, TYPE_CHECKING

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.database import MigrationSet, MongoConnector
from app.did_utils.comparisons import deep_equals
from app.did_utils.jsonld import DigitalArtefactVCInput, generate_digital_artefact_vc
from app.routers.basetypes import (
    UUIDString,
    DIDOrUUIDList,
    DivisionStr,
    CanonicalizedUUID,
    Multihash,
    division_did_from_division,
    division_from_str,
)
from app.services.exceptions import (
    ArtefactNoChangesError,
    ArtefactNotFoundError,
    DivisionKeysNotFound,
    DivisionMismatchError,
    ProvenanceNotFoundError,
    VersionConflictError,
)
from app.did_utils.eddsa import sign_vc
from app.services.vault_service import (
    VaultService,
    DivisionPublicKeysNotFoundError,
    SigningKeyNotFoundError,
)

if TYPE_CHECKING:
    pass


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


@dataclass
class ProvenanceNode:
    """Represents a node in the provenance tree.

    Attributes:
        uid: The UUID identifying the artefact (version_uid if found, otherwise the original provenance uid)
        division: The division identifier of the artefact, or None if not found
        truncated: True if the node has children but recursion was stopped (due to depth or child count limits)
        children: List of child ProvenanceNodes, or None if no children or not recursed
    """
    uid: str
    division: Optional[str]
    truncated: bool = False
    children: Optional[list["ProvenanceNode"]] = field(default=None)


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

# =============================================================================
# Utils/helpers
# =============================================================================
def _artefact_has_changes(
    existing: dict[str, Any],
    new_hash: Optional[str],
    new_metadata: Optional[Any],
    new_provenance: Optional[list[str]],
) -> bool:
    """Check if the new artefact data differs from the existing version.

    Compares artefact_hash, artefact_metadata (deep), and provenance list
    to determine if at least one field has changed.

    Args:
        existing: The existing artefact document from the database
        new_hash: The new artefact_hash value (or None)
        new_metadata: The new artefact_metadata value (or None)
        new_provenance: The new provenance list (or None)

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

    return False


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
        )

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
        # Production with dependency injection
        vault_svc = get_vault_service()
        db = MongoConnector.from_vault_service(vault_svc)
        did_svc = DIDService(db=db, vault_svc=vault_svc)

        # Testing with mocks
        mock_client = InMemoryVaultClient()
        vault_svc = VaultService(mock_client, "secret")
        db = MongoConnector.from_client(mongomock.MongoClient(), "test_db")
        did_svc = DIDService(db=db, vault_svc=vault_svc, run_migrations=True)
    """

    # Singleton reference (deprecated - use DI instead)
    _singleton_svc: ClassVar[Optional["DIDService"]] = None

    @classmethod
    def _get_instance(
        cls,
        db: MongoConnector,
        vault_svc: Optional[VaultService] = None,
    ) -> "DIDService":
        """Get or create the singleton DIDService instance.

        DEPRECATED: Prefer direct instantiation with dependency injection.

        Args:
            db: MongoConnector instance
            vault_svc: Optional VaultService instance. If None, uses get_vault_service().

        Returns:
            The singleton DIDService instance
        """
        if cls._singleton_svc is None:
            cls._singleton_svc = cls(db=db, vault_svc=vault_svc)
        return cls._singleton_svc

    @classmethod
    def _reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        cls._singleton_svc = None

    _artefacts_col_name = "did_artefacts"  # Collection name.

    db: MongoConnector
    _vault_svc: VaultService

    # List of divisions that must have signing keys provisioned. Currently
    # hardcoded, in the future we will have a management API endpoint to create
    # these.
    _required_divisions: ClassVar[list[str]] = ["advisory", "epdw"]

    def __init__(
        self,
        db: MongoConnector,
        vault_svc: Optional[VaultService] = None,
        run_migrations: bool = True,
        ensure_signing_keys: bool = True,
    ):
        """Initialize DIDService with injected dependencies.

        Args:
            db: MongoConnector instance for database operations
            vault_svc: VaultService instance for vault operations.
                       If None, will use get_vault_service() from vault module.
            run_migrations: Whether to run database migrations on init (default True)
            ensure_signing_keys: Whether to ensure division signing keys exist (default True)
        """
        self.db = db

        # Use provided vault service or get from module
        if vault_svc is not None:
            self._vault_svc = vault_svc
        else:
            from app.services.vault import get_vault_service
            self._vault_svc = get_vault_service()

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
                    new_division=artefact.division,
                )

            # Validate at least one thing changed (either artefact_hash,
            # artefact_metadata (deep) or provenance list).
            if not _artefact_has_changes(
                existing=latest_doc,
                new_hash=artefact.artefact_hash,
                new_metadata=artefact.artefact_metadata,
                new_provenance=list(artefact.provenance) if artefact.provenance else None,
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

    def find_by_external_uid(
        self, external_uid: UUIDString, division: DivisionStr | None = None
    ) -> Optional[ArtefactRecord]:
        """
        Find the latest version of an artefact by external_uid.

        Args:
            external_uid: The external UUID of the artefact
            division: Optional division identifier. If specified, the artefact
                      must match that division. If None, any division is acceptable.

        Returns:
            ArtefactRecord if found, None otherwise
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        query: dict[str, Any] = {"external_uid": external_uid}
        if division is not None:
            query["division"] = division

        doc = collection.find_one(query, sort=[("version", -1)])
        if doc is None:
            return None
        # Remove MongoDB _id before returning
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
        except DivisionPublicKeysNotFoundError:
            raise DivisionKeysNotFound(division=division)

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
        except SigningKeyNotFoundError:
            raise DivisionKeysNotFound(division=division)

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
    ) -> tuple[dict, Optional[dict]]:
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
                    truncated=False,
                    children=children if children else None,
                ))
            else:
                # Don't recurse - mark as truncated if it has children
                nodes.append(ProvenanceNode(
                    uid=artefact["version_uid"],
                    division=artefact.get("division"),
                    truncated=has_children,
                    children=None,
                ))

        return nodes

    # TODO: Add unit tests for this.
    def artefact_vc(self, division: DivisionStr | None, uid: UUIDString) -> dict:
        """Generates a Verifiable Credential with proofs for a Digital Artefact.

        This method creates a signed Verifiable Credential for the specified
        digital artefact. The VC is signed using EdDSA (Ed25519) Data Integrity
        proofs with the latest valid division key.

        Args:
            division: The division identifier or None if the artefact can be from any division.
            uid: The UUID of the artefact.

        Returns:
            A signed Verifiable Credential document with eddsa-rdfc-2022 proofs.

        Raises:
            ArtefactNotFoundError: If the artefact is not found.
            DivisionKeysNotFound: If no signing keys exist for the division.
            HTTPException: If signing fails.
        """
        collection = self.db.get_collection(self._artefacts_col_name)

        # Find the latest version of the artefact
        artefact = self._find_artefact_by_uid(uid, collection)

        # Check for division validity.
        if artefact is None:
            raise ArtefactNotFoundError(uid=uid, division=division)
        if artefact["division"] is None or artefact["division"] == "":
            # Should never happen - schema ensures division is not blank.
            raise RuntimeError("artefact does not have a division")
        elif division is None:
            # Any division acceptable. Use the one in the artefact.
            division = division_from_str(artefact["division"])
        elif artefact["division"] != division:
            # MUST be ArtefactNotFoundError to avoid leaking that the artefact
            # exists under a different division.
            raise ArtefactNotFoundError(uid=uid, division=division)

        # Build the DID for division.
        division_did = division_did_from_division(division)

        # Get the active signing key fragment for this division
        try:
            fragment = self._get_active_signing_key_fragment(division)
        except SigningKeyNotFoundError:
            raise DivisionKeysNotFound(division=division)


        # Create the unsigned VC for this DA.
        now = self.db.now()
        unsigned_vc = generate_digital_artefact_vc(
            format=artefact["format_version"],
            da=_artefact_to_da_vc_input(artefact),
            issuance_date=now,
        )

        # Fetch and use the signing key with secure cleanup
        # The signing_key_context ensures the key material is:
        # 1. Fetched from vault
        # 2. Converted to a SigningKey
        # 3. Cleared from memory after use via sodium_memzero
        try:
            with self._vault_svc.signing_key_context(division, fragment) as (signing_key, frag):
                verification_method = f"{division_did}#{frag}"

                return sign_vc(
                    vc=unsigned_vc,
                    secret_key=signing_key,
                    verification_method=verification_method,
                    created=now,
                )
        except SigningKeyNotFoundError:
            raise DivisionKeysNotFound(division=division)
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to sign VC for DA {uid} version {artefact['version']} division {division}: {e}",
            ) from e



# =============================================================================
# FastAPI Dependency Injection
# =============================================================================

def _get_db() -> MongoConnector:
    """FastAPI dependency to get MongoConnector instance.

    Uses the get_db() from app.routers.dependencies which handles
    lazy initialization via VaultService.
    """
    from app.routers.dependencies import get_db
    return get_db()


def _get_vault() -> VaultService:
    """FastAPI dependency to get VaultService instance.

    Uses the get_vault() from app.routers.dependencies which handles
    lazy initialization based on config.
    """
    from app.routers.dependencies import get_vault
    return get_vault()


# Type alias for MongoConnector dependency injection
MongoConnectorDep = Annotated[MongoConnector, Depends(_get_db)]

# Type alias for VaultService dependency injection
VaultServiceDep = Annotated[VaultService, Depends(_get_vault)]


def _get_DID_service(
    db: MongoConnectorDep,
    vault_svc: VaultServiceDep,
) -> DIDService:
    """FastAPI dependency to get DIDService instance with injected dependencies.

    Args:
        db: MongoConnector instance
        vault_svc: VaultService instance

    Returns:
        DIDService singleton instance
    """
    return DIDService._get_instance(db=db, vault_svc=vault_svc)


# Type alias for DIDService dependency injection
DIDServiceDep = Annotated[DIDService, Depends(_get_DID_service)]


@asynccontextmanager
async def did_service_lifespan() -> AsyncGenerator[None, None]:
    """Control lifespan of global DIDService instance.

    This is used by FastAPI's lifespan context to initialize
    the DIDService before handling requests.
    """
    from app.routers.dependencies import get_db, get_vault

    db = get_db()
    vault_svc = get_vault()
    DIDService._get_instance(db=db, vault_svc=vault_svc)
    try:
        yield
    finally:
        pass  # No shutdown procedure yet.
