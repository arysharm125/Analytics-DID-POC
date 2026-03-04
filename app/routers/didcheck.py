from datetime import datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.config import get_config
from app.did_utils.jsonld import canonicalize_document
from app.routers.basetypes import ArtefactTypeStr, DivisionStr, Multihash, PathUUID, UUIDString
from app.routers.dependencies import APITokenDep401Response, DIDCheckTokenDep, DIDServiceDep
from app.routers.responses import not_found_response
from app.services.did_service import ProvenanceNode as ServiceProvenanceNode

# ==========================
# Response Models
# ==========================

_example_random_uuid = f"{uuid4()}"


class BaseArtefactInfo(BaseModel):
    """Base fields shared between artefact info response models."""

    external_uid: UUIDString = Field(
        ...,
        description="UUID identifying the artefact across versions",
        examples=[_example_random_uuid],
    )
    version_uid: UUIDString = Field(
        ...,
        description="UUID identifying this specific version",
        examples=["b8ff3b79-863f-4fa9-84ba-0067663f2b04"],
    )
    version: int = Field(
        ...,
        description="Monotonically increasing version number",
        examples=[1, 3],
    )
    division: DivisionStr = Field(
        ...,
        description="Division identifier",
        examples=["advisory", "epdw"],
    )
    artefact_hash: Multihash | None = Field(
        default=None,
        description="Multihash identifying artefact content",
        examples=["QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"],
    )
    artefact_type: ArtefactTypeStr | None = Field(
        default=None,
        description="Optional artefact type identifier",
        examples=["report", "benchmark", "benchmark_iteration"],
    )
    backlink: str | None = Field(
        default=None,
        description="Optional URL back to the object in the originating system",
        examples=["https://example.com/reports/123"],
    )
    creation_date: datetime = Field(
        ...,
        description="Timestamp when this artefact version was created",
    )
    revoked: bool = Field(
        ...,
        description="Whether this artefact version is revoked",
        examples=[False],
    )
    update_message: str | None = Field(
        default=None,
        description="Optional message describing this update",
        examples=["Updated report data"],
    )
    updated_by: str | None = Field(
        default=None,
        description="Optional email of the person who made this update",
        examples=["user@amd.com"],
    )


class DigitalArtefactInfo(BaseArtefactInfo):
    """Information about a specific digital artefact version (overview, excludes metadata and provenance)."""

    has_provenance: bool = Field(
        ...,
        description="Whether this artefact has provenance records",
        examples=[True, False],
    )


class ProvenanceNode(BaseModel):
    """A node in the provenance tree."""

    uid: UUIDString = Field(
        ...,
        description="UUID of the provenance artefact",
        examples=["a1b2c3d4-e5f6-7890-abcd-ef1234567890"],
    )
    division: DivisionStr | None = Field(
        default=None,
        description="Division of the provenance artefact",
        examples=["advisory", "epdw"],
    )
    truncated: bool = Field(
        default=False,
        description="True if this node has children but wasn't recursed into (due to depth or count limits)",
    )
    children: list["ProvenanceNode"] | None = Field(
        default=None,
        description="Nested provenance items (children of this node)",
    )


class ProvenanceTreeResponse(BaseModel):
    """Response model for recursive provenance endpoint."""

    root_uid: UUIDString = Field(
        ...,
        description="UUID of the artefact whose provenance was queried",
    )
    max_depth: int = Field(
        ...,
        description="Maximum depth that was used for recursion",
    )
    max_children: int = Field(
        ...,
        description="Maximum children count threshold for recursion",
    )
    provenance: list[ProvenanceNode] = Field(
        ...,
        description="Direct provenance items of the root artefact",
    )


class FullArtefactInfo(BaseArtefactInfo):
    """Full information about a digital artefact version, including metadata."""

    artefact_metadata: Any | None = Field(
        default=None,
        description="Optional JSON metadata for the artefact",
    )
    provenance: list[UUIDString] | None = Field(
        default=None,
        description="List of provenance identifiers (normalized to UUIDs)",
        examples=[[]],
    )


class LatestVersionInfo(BaseModel):
    """Information about the latest version of an artefact (when queried version is not the latest)."""

    version_uid: UUIDString = Field(
        ...,
        description="UUID identifying the latest version",
        examples=["c9ff4c80-974g-5gb0-95cb-1178774g3c15"],
    )
    version: int = Field(
        ...,
        description="Version number of the latest version",
        examples=[5],
    )
    creation_date: datetime = Field(
        ...,
        description="Timestamp when the latest version was created",
    )
    revoked: bool = Field(
        ...,
        description="Whether the latest version is revoked",
        examples=[False],
    )


class VersionInfo(BaseModel):
    """Information about a single version of an artefact."""

    version: int = Field(
        ...,
        description="Version number",
        examples=[1, 2, 3],
    )
    version_uid: UUIDString = Field(
        ...,
        description="UUID identifying this specific version",
        examples=["b8ff3b79-863f-4fa9-84ba-0067663f2b04"],
    )
    creation_date: datetime = Field(
        ...,
        description="Timestamp when this version was created",
    )
    revoked: bool = Field(
        ...,
        description="Whether this version is revoked",
        examples=[False],
    )


class ArtefactVersionsResponse(BaseModel):
    """Response model for artefact versions endpoint."""

    external_uid: UUIDString = Field(
        ...,
        description="UUID identifying the artefact across versions",
        examples=[_example_random_uuid],
    )
    versions: list[VersionInfo] = Field(
        ...,
        description="List of all versions sorted by version number (ascending)",
    )


class DescendantInfo(BaseModel):
    """Information about a single descendant artefact."""

    uid: UUIDString = Field(
        ...,
        description="Version UID of the descendant",
        examples=["d9ff5c91-a85h-6hc1-a6dc-2289885h4d26"],
    )
    external_uid: UUIDString = Field(
        ...,
        description="External UID of the descendant",
        examples=[_example_random_uuid],
    )
    division: DivisionStr = Field(
        ...,
        description="Division of the descendant",
        examples=["advisory", "epdw"],
    )
    artefact_type: ArtefactTypeStr | None = Field(
        default=None,
        description="Artefact type of the descendant",
        examples=["report", "benchmark"],
    )
    version: int = Field(
        ...,
        description="Version number of the descendant",
        examples=[1, 2, 3],
    )
    creation_date: datetime = Field(
        ...,
        description="When this descendant version was created",
    )


class DescendantsResponse(BaseModel):
    """Response model for descendants endpoint with pagination."""

    root_uid: UUIDString = Field(
        ...,
        description="The UID that was queried for descendants",
        examples=[_example_random_uuid],
    )
    descendants: list[DescendantInfo] = Field(
        ...,
        description="List of descendant artefacts for this page",
    )
    total_count: int = Field(
        ...,
        description="Total number of descendants across all pages",
        examples=[42, 150],
    )
    page: int = Field(
        ...,
        description="Current page number (1-indexed)",
        examples=[1, 2, 3],
    )
    page_size: int = Field(
        ...,
        description="Number of items per page",
        examples=[20, 50],
    )
    has_more: bool = Field(
        ...,
        description="Whether there are more pages available",
        examples=[True, False],
    )


class DIDOverviewResponse(BaseModel):
    """Response model for DID overview endpoint."""

    digital_artefact: DigitalArtefactInfo = Field(
        ...,
        description="Information about the queried digital artefact",
    )
    latest_version: LatestVersionInfo | None = Field(
        default=None,
        description="Information about the latest version, if the queried version is not the latest",
    )


# ==========================
# Router
# ==========================
app = APIRouter(tags=["DID Check"], prefix="/didcheck")


@app.get("/{uid}/vc.json", responses={**APITokenDep401Response, **not_found_response()})
def artefact_vc(
    uid: PathUUID,
    api_token: DIDCheckTokenDep,
    did_svc: DIDServiceDep,
):
    """Return a Verifiable Credential with proofs for a Digital Artefact."""
    return did_svc.issue_artefact_vc(division=None, uid=uid)


@app.get("/{uid}/overview", responses={**APITokenDep401Response, **not_found_response()}, response_model_exclude_none=True)
def did_overview(
    uid: PathUUID,
    api_token: DIDCheckTokenDep,
    did_svc: DIDServiceDep,
) -> DIDOverviewResponse:
    """Return basic information about a digital artefact.

    Returns the artefact details including external_uid, version_uid, version,
    division, artefact_hash, provenance, creation_date, and revoked status.

    If a newer version of the artefact exists (identified by the same external_uid),
    the response also includes information about the latest version.
    """
    artefact, latest_version = did_svc.get_artefact_overview(uid)

    # Determine if artefact has provenance
    provenance_list = artefact.get("provenance")
    has_provenance = bool(provenance_list and len(provenance_list) > 0)

    # Build digital_artefact response (excludes artefact_metadata and provenance)
    digital_artefact = DigitalArtefactInfo(
        external_uid=artefact["external_uid"],
        version_uid=artefact["version_uid"],
        version=artefact["version"],
        division=artefact["division"],
        artefact_hash=artefact.get("artefact_hash"),
        artefact_type=artefact.get("artefact_type"),
        backlink=artefact.get("backlink"),
        creation_date=artefact["created_at"],
        revoked=artefact.get("revoked", False),
        has_provenance=has_provenance,
        update_message=artefact.get("update_message"),
        updated_by=artefact.get("updated_by"),
    )

    # Build latest_version response if applicable
    latest_version_info = None
    if latest_version is not None:
        latest_version_info = LatestVersionInfo(
            version_uid=latest_version["version_uid"],
            version=latest_version["version"],
            creation_date=latest_version["created_at"],
            revoked=latest_version.get("revoked", False),
        )

    return DIDOverviewResponse(
        digital_artefact=digital_artefact,
        latest_version=latest_version_info,
    )


@app.get(
    "/{uid}/artefact.json",
    responses={**APITokenDep401Response, **not_found_response()},
    response_model_exclude_none=True,
)
def artefact_full(
    uid: PathUUID,
    api_token: DIDCheckTokenDep,
    did_svc: DIDServiceDep,
) -> FullArtefactInfo:
    """Return the full digital artefact data including metadata.

    Returns all artefact fields including external_uid, version_uid, version,
    division, artefact_hash, artefact_metadata, provenance, creation_date,
    and revoked status.
    """
    artefact, _ = did_svc.get_artefact_overview(uid)

    return FullArtefactInfo(
        external_uid=artefact["external_uid"],
        version_uid=artefact["version_uid"],
        version=artefact["version"],
        division=artefact["division"],
        artefact_hash=artefact.get("artefact_hash"),
        artefact_metadata=artefact.get("artefact_metadata"),
        artefact_type=artefact.get("artefact_type"),
        backlink=artefact.get("backlink"),
        provenance=artefact.get("provenance"),
        creation_date=artefact["created_at"],
        revoked=artefact.get("revoked", False),
        update_message=artefact.get("update_message"),
        updated_by=artefact.get("updated_by"),
    )


def _service_node_to_response(node: ServiceProvenanceNode) -> ProvenanceNode:
    """Convert a ProvenanceNode dataclass from DIDService to the Pydantic response model."""
    children = None
    if node.children:
        children = [_service_node_to_response(child) for child in node.children]

    return ProvenanceNode(
        uid=node.uid,
        division=node.division,
        truncated=node.truncated,
        children=children,
    )


@app.get(
    "/{uid}/provenance",
    responses={**APITokenDep401Response, **not_found_response()},
)
def artefact_provenance(
    uid: PathUUID,
    api_token: DIDCheckTokenDep,
    did_svc: DIDServiceDep,
) -> ProvenanceTreeResponse:
    """Return the recursive provenance tree for a digital artefact.
    Nodes that have children but weren't recursed into are marked with truncated=True.
    """

    # These limits are hard coded for now to avoid exposing the possibility of
    # recursing too deeply or widely.
    depth = 3 # Maximum depth to recurse into provenance
    max_children = 10 # Maximum children count before truncating recursion

    provenance_tree = did_svc.get_provenance_tree(
        uid=uid,
        max_depth=depth,
        max_children=max_children,
    )

    # Convert service dataclass nodes to Pydantic response models
    provenance_nodes = [_service_node_to_response(node) for node in provenance_tree]

    return ProvenanceTreeResponse(
        root_uid=uid,
        max_depth=depth,
        max_children=max_children,
        provenance=provenance_nodes,
    )


@app.get(
    "/{uid}/versions",
    responses={**APITokenDep401Response, **not_found_response()},
)
def artefact_versions(
    uid: PathUUID,
    api_token: DIDCheckTokenDep,
    did_svc: DIDServiceDep,
) -> ArtefactVersionsResponse:
    """Return all versions of a digital artefact.

    Returns a list of all versions for the artefact identified by the given UID.
    The versions are sorted by version number in ascending order (oldest first).

    Args:
        uid: The artefact's version_uid or external_uid

    Returns:
        ArtefactVersionsResponse with external_uid and list of all versions
    """
    versions = did_svc.get_all_versions(uid)

    # Get external_uid from the first version (all versions share the same external_uid)
    external_uid = versions[0]["external_uid"] if versions else uid

    # Convert to VersionInfo models
    version_infos = [
        VersionInfo(
            version=v["version"],
            version_uid=v["version_uid"],
            creation_date=v["created_at"],
            revoked=v.get("revoked", False),
        )
        for v in versions
    ]

    return ArtefactVersionsResponse(
        external_uid=external_uid,
        versions=version_infos,
    )


@app.get(
    "/{uid}/descendants",
    responses={**APITokenDep401Response, **not_found_response()},
)
def artefact_descendants(
    uid: PathUUID,
    api_token: DIDCheckTokenDep,
    did_svc: DIDServiceDep,
    page: int = 1,
    page_size: int = 20,
) -> DescendantsResponse:
    """Return paginated descendants of a digital artefact.

    Returns artefacts that have this UID in their provenance (i.e., objects
    derived from this artefact). Only the latest version of each descendant
    is returned, sorted by creation date (newest first).

    Args:
        uid: The artefact's version_uid or external_uid
        page: Page number (1-indexed, default: 1)
        page_size: Number of items per page (1-100, default: 20)

    Returns:
        DescendantsResponse with paginated list of descendants and metadata
    """
    # Validate pagination parameters
    if page < 1:
        raise HTTPException(status_code=422, detail="Page must be >= 1")
    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="Page size must be between 1 and 100")

    # Get paginated descendants from service
    result = did_svc.get_descendants_paginated(
        uid=uid,
        page=page,
        page_size=page_size,
    )

    # Convert DescendantNode dataclasses to Pydantic models
    descendant_infos = [
        DescendantInfo(
            uid=desc.uid,
            external_uid=desc.external_uid,
            division=desc.division,
            artefact_type=desc.artefact_type,
            version=desc.version,
            creation_date=desc.creation_date,
        )
        for desc in result.descendants
    ]

    return DescendantsResponse(
        root_uid=result.root_uid,
        descendants=descendant_infos,
        total_count=result.total_count,
        page=result.page,
        page_size=result.page_size,
        has_more=result.has_more,
    )


# ==========================
# Debug Endpoint - VC Canonicalization
# ==========================

@app.get(
    "/{uid}/vc.nq",
    response_class=PlainTextResponse,
    responses={**APITokenDep401Response, **not_found_response()},
    tags=["Debug"],
)
def artefact_vc_nquads(
    uid: PathUUID,
    api_token: DIDCheckTokenDep,
    did_svc: DIDServiceDep,
) -> str:
    """[DEBUG] Return the canonicalized VC in N-Quads format.

    This endpoint returns the canonicalized (URDNA2015/RDFC-1.0) representation
    of the Verifiable Credential without the proof. This is useful for debugging
    signature verification issues by comparing the backend's canonicalization
    with the frontend's.

    The endpoint is only available when the FEATURE_DEBUG_VC_NQUADS environment
    variable is set.

    Returns:
        Plain text N-Quads representation of the VC (without proof)
    """
    # Check feature flag
    if not get_config().features.debug_vc_nquads:
        raise HTTPException(
            status_code=404,
            detail="Debug VC N-Quads endpoint is not enabled"
        )

    # Get the signed VC
    vc = did_svc.issue_artefact_vc(division=None, uid=uid)

    # Remove the proof for canonicalization
    vc_without_proof = {k: v for k, v in vc.items() if k != "proof"}

    # Canonicalize to N-Quads
    nquads = canonicalize_document(vc_without_proof)

    return nquads


# ==========================
# Division DID Document Endpoint
# ==========================

# Path parameter type for division
PathDivision = Annotated[
    DivisionStr,
    Path(
        description="Division identifier (e.g., 'advisory', 'epdw')",
        examples=["advisory", "epdw"],
    ),
]


@app.get("/{division}/did.json", responses={**APITokenDep401Response, **not_found_response("Division")})
def division_did_document(
    division: PathDivision,
    api_token: DIDCheckTokenDep,
    did_svc: DIDServiceDep,
):
    """Return the DID document for a division.

    The DID document contains the public verification keys used to verify
    digital artefacts signed by this division. The document follows the
    W3C DID specification and includes:

    - The division's DID identifier (did:web:did.amd.com:{division})
    - Verification methods (public keys in Multikey format)
    - Assertion method references for credential signing
    """
    return did_svc.division_did_doc(division)
