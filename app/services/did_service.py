from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, AsyncGenerator, ClassVar, Optional

from attr import dataclass
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError
from nacl.signing import SigningKey

from app.database import MigrationSet, MongoConnector, get_global_db
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
    ArtefactNotFoundError,
    DivisionKeysNotFound,
    DivisionMismatchError,
    ProvenanceNotFoundError,
    VersionConflictError,
)
from app.did_utils.eddsa import (
    create_keypair_from_hex,
    get_public_key_multibase,
    secure_signing_context,
    sign_vc,
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
def _artefact_to_da_vc_input(artefact : dict[str, Any]) -> DigitalArtefactVCInput:
    return DigitalArtefactVCInput(
            uid=artefact["external_uid"],
            version=artefact["version"],
            version_uid=artefact["version_uid"],
            hash=artefact["artefact_hash"],
            metadata=artefact["artefact_metadata"],
            created_at=artefact["created_at"],
            division=artefact["division"],
            provenance=artefact["provenance"],
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

    _artefacts_col_name = "did_artefacts" # Collection name.

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

    def _fetch_division_pub_keys(self, division: str) -> list[dict]:
        """Fetch the public keys for a division.

        TODO: Fetch the list from DB. For now, just use a hardcoded key.

        Args:
            division: The division identifier.

        Returns:
            List of key information dictionaries, each containing:
                - secret_key_hex: The Ed25519 seed as hex string (32 bytes)
                - fragment: The key fragment identifier
                - signing_key: The Ed25519 SigningKey derived from the seed
                - public_key_multibase: The public key in multibase format

        Raises:
            DivisionKeyNotFound: If not keys are found registered for the division.
        """

        if division != "advisory":
            raise DivisionKeysNotFound(division=division)

        # Hardcoded Ed25519 key for now - in production this would be fetched from a secure store
        # Generated using: secrets.token_hex(32)
        secret_key_hex = "a2c4e6f8b0d1c3e5a7f9b1d3c5e7a9f0b2d4c6e8a0f1b3d5c7e9a1f3b5d7c9e1"
        fragment = "key20260204"

        signing_key = create_keypair_from_hex(secret_key_hex)
        public_key_multibase = get_public_key_multibase(signing_key)

        return [
            {
                "secret_key_hex": secret_key_hex,
                "fragment": fragment,
                "public_key_multibase": public_key_multibase,
            }
        ]

    @dataclass
    class _PrivateKeyInfo:
        fragment : str
        key : SigningKey

    def _fetch_division_priv_key(self, division: DivisionStr) -> _PrivateKeyInfo:
        # Hardcoded Ed25519 key for now - in production this would be fetched from a secure store
        # Generated using: secrets.token_hex(32)
        secret_key_hex = "a2c4e6f8b0d1c3e5a7f9b1d3c5e7a9f0b2d4c6e8a0f1b3d5c7e9a1f3b5d7c9e1"
        fragment = "key20260204"
        return DIDService._PrivateKeyInfo(fragment, create_keypair_from_hex(secret_key_hex))

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

    # TODO: Add unit tests for this.
    def artefact_vc(self, division: DivisionStr | None, uid: UUIDString) -> dict:
        """Generates a Verifiable Credential  with proofs for a Digital Artefact.

        This method creates a signed Verifiable Credential for the specified
        digital artefact. The VC is signed using EdDSA (Ed25519) Data Integrity
        proofs with the latest valid division key.

        Args:
            division: The division identifier or None if the artefact can be from any division.
            uid: The UUID of the artefact.

        Returns:
            A signed Verifiable Credential  document with eddsa-rdfc-2022 proofs.

        Raises:
            HTTPException: If the artefact is not found or signing fails.
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
            raise ArtefactNotFoundError(uid=uid, division=division)

        # Build the DID for this artefact
        division_did = division_did_from_division(division)

        # Create the unsigned VC for this DA.
        unsigned_vc = generate_digital_artefact_vc(
            format=artefact["format_version"],
            da=_artefact_to_da_vc_input(artefact),
            issuance_date=self.db.now(),
        )

        # Use the latest available key for signing
        sign_key = self._fetch_division_priv_key(division)

        # Sign the VC with EdDSA using secure context to ensure key cleanup
        # The secure_signing_context guarantees the key material is cleared
        # from memory after signing, regardless of success or failure
        with secure_signing_context(sign_key.key) as secret_key:
            # Build verification method URL
            # TODO: build this earlier, when determining the public key.
            verification_method = f"{division_did}#{sign_key.fragment}"

            try:
                return sign_vc(
                    vc=unsigned_vc,
                    secret_key=secret_key,
                    verification_method=verification_method,
                )
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to sign VC for DA ${uid} version ${artefact['version']} division ${division}: {e}",
                ) from e



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
