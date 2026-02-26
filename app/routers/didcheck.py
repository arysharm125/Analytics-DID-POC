from datetime import datetime
from typing import Annotated, Any, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.config import get_config
from app.did_utils.jsonld import canonicalize_document
from app.routers.basetypes import ArtefactTypeStr, DivisionStr, Multihash, UUIDString
from app.routers.dependencies import DIDCheckTokenDep, DIDServiceDep, APITokenDep401Response
from app.routers.epdw import PathUUID
from app.services.did_service import ProvenanceNode as ServiceProvenanceNode

# ==========================
# Response Models
# ==========================

_example_random_uuid = f"{uuid4()}"


class DigitalArtefactInfo(BaseModel):
    """Information about a specific digital artefact version (overview, excludes metadata and provenance)."""

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
    artefact_hash: Optional[Multihash] = Field(
        default=None,
        description="Multihash identifying artefact content",
        examples=["QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"],
    )
    artefact_type: Optional[ArtefactTypeStr] = Field(
        default=None,
        description="Optional artefact type identifier",
        examples=["report", "benchmark", "benchmark_iteration"],
    )
    backlink: Optional[str] = Field(
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
    division: Optional[DivisionStr] = Field(
        default=None,
        description="Division of the provenance artefact",
        examples=["advisory", "epdw"],
    )
    truncated: bool = Field(
        default=False,
        description="True if this node has children but wasn't recursed into (due to depth or count limits)",
    )
    children: Optional[list["ProvenanceNode"]] = Field(
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


class FullArtefactInfo(BaseModel):
    """Full information about a digital artefact version, including metadata."""

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
    artefact_hash: Optional[Multihash] = Field(
        default=None,
        description="Multihash identifying artefact content",
        examples=["QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"],
    )
    artefact_metadata: Optional[Any] = Field(
        default=None,
        description="Optional JSON metadata for the artefact",
    )
    artefact_type: Optional[ArtefactTypeStr] = Field(
        default=None,
        description="Optional artefact type identifier",
        examples=["report", "benchmark", "benchmark_iteration"],
    )
    backlink: Optional[str] = Field(
        default=None,
        description="Optional URL back to the object in the originating system",
        examples=["https://example.com/reports/123"],
    )
    provenance: Optional[list[UUIDString]] = Field(
        default=None,
        description="List of provenance identifiers (normalized to UUIDs)",
        examples=[[]],
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


class DIDOverviewResponse(BaseModel):
    """Response model for DID overview endpoint."""

    digital_artefact: DigitalArtefactInfo = Field(
        ...,
        description="Information about the queried digital artefact",
    )
    latest_version: Optional[LatestVersionInfo] = Field(
        default=None,
        description="Information about the latest version, if the queried version is not the latest",
    )


# Response documentation for 404 Not Found errors
NotFoundResponse = {
    404: {
        "description": "Artefact not found",
        "content": {
            "application/json": {
                "examples": {
                    "not_found": {
                        "summary": "Artefact not found",
                        "value": {
                            "detail": "Artefact with uid 'b8ff3b79-863f-4fa9-84ba-0067663f2b04' not found in any division"
                        }
                    }
                }
            }
        },
    }
}

# ==========================
# Router
# ==========================
app = APIRouter(tags=["DID Check"], prefix="/didcheck")


@app.get("/{uid}/vc.json", responses={**APITokenDep401Response})
def artefact_vc(
    uid: PathUUID,
    api_token: DIDCheckTokenDep,
    did_svc: DIDServiceDep,
):
    """Return a Verifiable Credential with proofs for a Digital Artefact."""
    return did_svc.issue_artefact_vc(division=None, uid=uid)


@app.get("/{uid}/overview", responses={**APITokenDep401Response, **NotFoundResponse}, response_model_exclude_none=True)
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
    responses={**APITokenDep401Response, **NotFoundResponse},
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
    responses={**APITokenDep401Response, **NotFoundResponse},
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


# ==========================
# Debug Endpoint - VC Canonicalization
# ==========================

@app.get(
    "/{uid}/vc.nq",
    response_class=PlainTextResponse,
    responses={**APITokenDep401Response, **NotFoundResponse},
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


@app.get("/{division}/did.json", responses={**APITokenDep401Response})
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
