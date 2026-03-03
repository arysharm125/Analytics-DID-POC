"""JSON-LD utilities for VC/VP canonicalization.

This module provides functions for converting Verifiable Credentials and
Verifiable Presentations to canonical N-Quads format for Data Integrity
signatures using the W3C VC Data Integrity specification.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pyld import jsonld

from app.routers.basetypes import (
    DIDList,
    DivisionStr,
    Multihash,
    UUIDString,
    did_from_uuid,
    did_list_from_uuid_list,
    division_did_from_division,
)

# Mapping of context URLs to local JSON files
_CONTEXT_FILES = {
    "https://www.w3.org/2018/credentials/v1": "credentials-v1.json",
    "https://did.amd.com/contexts/digitalArtefacts/v1": "digital-artefacts-v1.json",
    "https://w3id.org/security/data-integrity/v2": "data-integrity-v2.json",
}

# Data Integrity context URL
DATA_INTEGRITY_V2_CONTEXT = "https://w3id.org/security/data-integrity/v2"

# Cache for loaded contexts
_context_cache: dict[str, dict] = {}


def _get_contexts_path() -> Path:
    """Get the path to the contexts directory."""
    return Path(__file__).parents[2] / "contexts"


def _load_context(url: str) -> dict | None:
    """Load a context from the local JSON file.

    Args:
        url: The context URL to load

    Returns:
        The loaded context dictionary, or None if not found
    """
    if url in _context_cache:
        return _context_cache[url]

    filename = _CONTEXT_FILES.get(url)
    if filename is None:
        return None

    context_path = _get_contexts_path() / filename
    if not context_path.exists():
        return None

    with open(context_path, encoding="utf-8") as f:
        context = json.load(f)

    _context_cache[url] = context
    return context


def _load_all_contexts() -> dict[str, dict]:
    """Load all built-in contexts.

    Returns:
        Dictionary mapping context URLs to their content
    """
    contexts = {}
    for url in _CONTEXT_FILES:
        context = _load_context(url)
        if context is not None:
            contexts[url] = context
    return contexts


# Load contexts at module import time for backwards compatibility
VC_CONTEXTS = _load_all_contexts()


def _custom_document_loader(url: str, options: dict | None = None) -> dict:
    """Custom JSON-LD document loader that uses local context definitions.

    Args:
        url: The URL to load
        options: Optional loading options

    Returns:
        Document loader response with context
    """
    context = _load_context(url)
    if context is not None:
        return {
            "contentType": "application/ld+json",
            "contextUrl": None,
            "document": context,
            "documentUrl": url
        }

    # Fall back to default loader for other URLs
    # In production, you might want to cache or restrict this
    return jsonld.load_document(url, options)


def canonicalize_document(document: dict) -> str:
    """Convert a JSON-LD document to canonical N-Quads format.

    Uses the URDNA2015 canonicalization algorithm as required by
    the W3C VC Data Integrity specification.

    Args:
        document: The JSON-LD document to canonicalize

    Returns:
        The document in canonical N-Quads format as a string
    """
    options = {
        "algorithm": "URDNA2015",
        "format": "application/n-quads",
        "documentLoader": _custom_document_loader
    }

    return str(jsonld.normalize(document, options))


def _document_to_messages(document: dict) -> list[str]:
    """Convert a JSON-LD document to a list of N-Quad statements.

    Args:
        document: The JSON-LD document to convert

    Returns:
        A list of N-Quad statements (strings)
    """
    nquads = canonicalize_document(document)

    # Split into individual statements, filtering empty lines
    statements = [
        stmt.strip()
        for stmt in nquads.split('\n')
        if stmt.strip()
    ]

    return statements


def prepare_vc_for_signing(vc: dict) -> tuple[dict, list[str]]:
    """Prepare a Verifiable Credential for signing.

    This removes any existing proof and converts the document to
    N-Quad messages suitable for signing.

    Args:
        vc: The Verifiable Credential to prepare

    Returns:
        A tuple of (VC without proof, list of N-Quad messages)
    """
    # Create a copy without the proof
    vc_without_proof = {k: v for k, v in vc.items() if k != "proof"}

    # Ensure Data Integrity v2 context is included for proper canonicalization
    contexts = vc_without_proof.get("@context", [])
    if isinstance(contexts, str):
        contexts = [contexts]
    if DATA_INTEGRITY_V2_CONTEXT not in contexts:
        contexts = [*list(contexts), DATA_INTEGRITY_V2_CONTEXT]
        vc_without_proof["@context"] = contexts

    # Convert to N-Quad messages
    messages = _document_to_messages(vc_without_proof)

    return vc_without_proof, messages


def prepare_vp_for_signing(vp: dict) -> tuple[dict, list[str]]:
    """Prepare a Verifiable Presentation for signing.

    This removes any existing proof from the VP (but keeps VC proofs)
    and converts the document to N-Quad messages.

    Args:
        vp: The Verifiable Presentation to prepare

    Returns:
        A tuple of (VP without proof, list of N-Quad messages)
    """
    # Create a copy without the VP-level proof
    vp_without_proof = {k: v for k, v in vp.items() if k != "proof"}

    # Ensure Data Integrity v2 context is included
    contexts = vp_without_proof.get("@context", [])
    if isinstance(contexts, str):
        contexts = [contexts]
    if DATA_INTEGRITY_V2_CONTEXT not in contexts:
        contexts = [*list(contexts), DATA_INTEGRITY_V2_CONTEXT]
        vp_without_proof["@context"] = contexts

    # Convert to N-Quad messages
    messages = _document_to_messages(vp_without_proof)

    return vp_without_proof, messages


def create_proof_options(
    verification_method: str,
    proof_purpose: str = "assertionMethod",
    created: str | None = None,
    cryptosuite: str = "eddsa-rdfc-2022"
) -> dict:
    """Create proof options for Data Integrity signature.

    Args:
        verification_method: The DID URL of the verification method
        proof_purpose: The purpose of the proof (default: assertionMethod)
        created: ISO 8601 timestamp (generated if not provided)
        cryptosuite: The cryptosuite to use (default: eddsa-rdfc-2022)

    Returns:
        Proof options dictionary for Data Integrity proof
    """
    from datetime import datetime, timezone

    if created is None:
        created = datetime.now(timezone.utc).isoformat()

    return {
        "@context": DATA_INTEGRITY_V2_CONTEXT,
        "type": "DataIntegrityProof",
        "cryptosuite": cryptosuite,
        "created": created,
        "verificationMethod": verification_method,
        "proofPurpose": proof_purpose
    }


def proof_options_to_messages(proof_options: dict) -> list[str]:
    """Convert proof options to N-Quad messages.

    The proof options are canonicalized separately and included
    in the signature.

    Args:
        proof_options: The proof options dictionary

    Returns:
        List of N-Quad messages for the proof options
    """
    return _document_to_messages(proof_options)


@dataclass
class DigitalArtefactVCInput:
    """Input data that is necessary to generate a Digital Artefact VC.

    Note: provenance is stored as DIDOrUUIDList (canonicalized to UUIDs) but
    is coerced to DIDList when generating the VC.
    """
    uid: UUIDString
    version: int
    version_uid: UUIDString
    hash: Multihash | None
    metadata: Any | None
    created_at: datetime
    division: DivisionStr
    provenance: DIDList | None
    artefact_type: str | None = None
    update_message: str | None = None
    updated_by: str | None = None


def generate_digital_artefact_vc(
        format: int,
        da: DigitalArtefactVCInput,
        issuance_date: datetime,
        vc_id: UUIDString | None = None,
    ) -> dict[str, Any]:
    """
    Generates an unsigned Verifiable Credential for a Digital Artefact, as
    identified by a given UUID.

    Arguments:
        format: One of the supported format versions.
        da: Information about the digital artefact.
        issuance_date: Issuance date to use.
        vc_id: Optional UUID for the VC's own identifier (as a DID).
               If provided, the VC will include an 'id' field.

    Returns:
        The structured, unsigned VC.
    """

    # Future proof format changes. Every format version *MUST* be generated
    # in the same way, otherwise validation may fail in the future.
    # This means that any time we need to change the structure of the VC (e.g.
    # add new fields to credentialSubject), add new context entries, etc
    # we need to bump the format version and create an entirely new version.
    # Please do this only sporadically.
    if format != 1:
        raise RuntimeError("Only format 1 VCs is currently supported")

    vc = {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://did.amd.com/contexts/digitalArtefacts/v1",
            DATA_INTEGRITY_V2_CONTEXT,
        ],
        "type": ["VerifiableCredential", "DigitalArtefactCredential"],
        **({"id": did_from_uuid(vc_id)} if vc_id is not None else {}),
        "issuer": division_did_from_division(da.division),
        "issuanceDate": issuance_date.isoformat(),
        "credentialSubject": {
            "id": did_from_uuid(da.uid),
            "version": da.version,
            "versionUid": did_from_uuid(da.version_uid),
            "creationDate": da.created_at.isoformat(),
            **({"artefactType": da.artefact_type} if da.artefact_type is not None else {}),
            **({"artefactHash": str(da.hash)} if da.hash is not None else {}),
            **({"updateMessage": da.update_message} if da.update_message is not None else {}),
            **({"updatedBy": da.updated_by} if da.updated_by is not None else {}),
            **({"artefactMetadata": da.metadata} if da.metadata is not None else {}),
            **({"provenance": did_list_from_uuid_list(da.provenance)} if da.provenance is not None else {}),
        }
    }

    return vc
