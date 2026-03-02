"""Generate VC fixtures for frontend compatibility testing.

This test generates VCs using the Python backend and exports them as JSON
fixtures for verification by the JavaScript frontend.

Run with: pytest -m vc_compat
"""

import json
from pathlib import Path

import pytest

from app.did_utils.jsonld import canonicalize_document
from app.routers.basetypes import did_from_uuid
from app.services.did_service import ArtefactInput


@pytest.mark.vc_compat
def test_generate_basic_advisory_vc(did_service_no_migrations_with_keys, fixtures_dir: Path, vcs_dir: Path):
    """Generate a basic advisory VC with minimal fields."""
    # Create an artefact with known UUID
    artefact_uuid = "11111111-1111-1111-1111-111111111111"

    artefact_input = ArtefactInput(
        external_uid=artefact_uuid,
        division="advisory",
        artefact_type="report",
    )

    record = did_service_no_migrations_with_keys.upsert_artefact(artefact_input)

    # Issue VC
    vc = did_service_no_migrations_with_keys.issue_artefact_vc(
        division="advisory",
        uid=record.version_uid,
    )

    # Save VC to fixtures
    fixture_path = vcs_dir / "advisory_basic.json"
    with open(fixture_path, "w") as f:
        json.dump(vc, f, indent=2, default=str)

    # Verify structure
    assert vc["type"] == ["VerifiableCredential", "DigitalArtefactCredential"]
    assert vc["issuer"] == "did:web:did.amd.com:advisory"
    assert vc["credentialSubject"]["id"] == did_from_uuid(artefact_uuid)
    assert "proof" in vc
    assert vc["proof"]["type"] == "DataIntegrityProof"
    assert vc["proof"]["cryptosuite"] == "eddsa-rdfc-2022"


@pytest.mark.vc_compat
def test_generate_epdw_vc_with_metadata(did_service_no_migrations_with_keys, fixtures_dir: Path, vcs_dir: Path):
    """Generate an EPDW VC with artefact metadata."""
    artefact_uuid = "22222222-2222-2222-2222-222222222222"

    artefact_input = ArtefactInput(
        external_uid=artefact_uuid,
        division="epdw",
        artefact_type="benchmark",
        artefact_metadata={
            "benchmark_name": "SPEC CPU 2017",
            "score": 450.5,
            "timestamp": "2024-01-15T10:30:00Z",
        },
    )

    record = did_service_no_migrations_with_keys.upsert_artefact(artefact_input)

    # Issue VC
    vc = did_service_no_migrations_with_keys.issue_artefact_vc(
        division="epdw",
        uid=record.version_uid,
    )

    # Save VC to fixtures
    fixture_path = vcs_dir / "epdw_with_metadata.json"
    with open(fixture_path, "w") as f:
        json.dump(vc, f, indent=2, default=str)

    # Verify structure
    assert vc["issuer"] == "did:web:did.amd.com:epdw"
    assert vc["credentialSubject"]["artefactMetadata"] == artefact_input.artefact_metadata


@pytest.mark.vc_compat
def test_generate_vc_with_hash(did_service_no_migrations_with_keys, fixtures_dir: Path, vcs_dir: Path):
    """Generate a VC with artefact hash."""
    artefact_uuid = "33333333-3333-3333-3333-333333333333"

    artefact_input = ArtefactInput(
        external_uid=artefact_uuid,
        division="advisory",
        artefact_type="report",
        artefact_hash="QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG",
    )

    record = did_service_no_migrations_with_keys.upsert_artefact(artefact_input)

    # Issue VC
    vc = did_service_no_migrations_with_keys.issue_artefact_vc(
        division="advisory",
        uid=record.version_uid,
    )

    # Save VC to fixtures
    fixture_path = vcs_dir / "advisory_with_hash.json"
    with open(fixture_path, "w") as f:
        json.dump(vc, f, indent=2, default=str)

    # Verify structure
    assert vc["credentialSubject"]["artefactHash"] == artefact_input.artefact_hash


@pytest.mark.vc_compat
def test_generate_vc_with_provenance(did_service_no_migrations_with_keys, fixtures_dir: Path, vcs_dir: Path):
    """Generate a VC with provenance chain."""
    # Create parent artefact
    parent_uuid = "44444444-4444-4444-4444-444444444444"
    parent_input = ArtefactInput(
        external_uid=parent_uuid,
        division="epdw",
        artefact_type="sut",
    )
    parent_record = did_service_no_migrations_with_keys.upsert_artefact(parent_input)

    # Create child artefact with provenance
    child_uuid = "55555555-5555-5555-5555-555555555555"
    child_input = ArtefactInput(
        external_uid=child_uuid,
        division="epdw",
        artefact_type="benchmark",
        provenance=[parent_record.version_uid],
    )
    child_record = did_service_no_migrations_with_keys.upsert_artefact(child_input)

    # Issue VC for child
    vc = did_service_no_migrations_with_keys.issue_artefact_vc(
        division="epdw",
        uid=child_record.version_uid,
    )

    # Save VC to fixtures
    fixture_path = vcs_dir / "epdw_with_provenance.json"
    with open(fixture_path, "w") as f:
        json.dump(vc, f, indent=2, default=str)

    # Verify structure
    # Note: Provenance is stored as DIDs in the VC
    assert vc["credentialSubject"]["provenance"] == [did_from_uuid(parent_record.version_uid)]


@pytest.mark.vc_compat
def test_generate_vc_complex(did_service_no_migrations_with_keys, fixtures_dir: Path, vcs_dir: Path):
    """Generate a complex VC with all optional fields."""
    artefact_uuid = "66666666-6666-6666-6666-666666666666"

    artefact_input = ArtefactInput(
        external_uid=artefact_uuid,
        division="advisory",
        artefact_type="security-report",
        artefact_hash="QmT5NvUtoM5nWFfrQdVrFtvGfKFmG7AHE8P34isapyhCxX",
        artefact_metadata={
            "severity": "high",
            "cve_ids": ["CVE-2024-1234", "CVE-2024-5678"],
            "affected_products": ["Product A", "Product B"],
        },
        backlink="https://security.amd.com/reports/2024-001",
    )

    record = did_service_no_migrations_with_keys.upsert_artefact(artefact_input)

    # Issue VC
    vc = did_service_no_migrations_with_keys.issue_artefact_vc(
        division="advisory",
        uid=record.version_uid,
    )

    # Save VC to fixtures
    fixture_path = vcs_dir / "advisory_complex.json"
    with open(fixture_path, "w") as f:
        json.dump(vc, f, indent=2, default=str)

    # Verify all fields present
    subject = vc["credentialSubject"]
    assert subject["artefactType"] == "security-report"
    assert subject["artefactHash"] == artefact_input.artefact_hash
    assert subject["artefactMetadata"] == artefact_input.artefact_metadata


@pytest.mark.vc_compat
def test_export_did_documents(did_service_no_migrations_with_keys, fixtures_dir: Path):
    """Export DID documents for all divisions."""
    divisions = ["advisory", "epdw"]

    for division in divisions:
        did_doc = did_service_no_migrations_with_keys.division_did_doc(division)

        # Save DID document
        fixture_path = fixtures_dir / f"{division}_did.json"
        with open(fixture_path, "w") as f:
            json.dump(did_doc, f, indent=2)

        # Verify structure
        assert did_doc["id"] == f"did:web:did.amd.com:{division}"
        assert "@context" in did_doc
        assert "verificationMethod" in did_doc
        assert "assertionMethod" in did_doc
        assert len(did_doc["verificationMethod"]) > 0


@pytest.mark.vc_compat
def test_export_canonical_nquads(fixtures_dir: Path, vcs_dir: Path):
    """Export canonical N-Quads for each VC for comparison with JavaScript.

    This exports the canonicalized form (without proof) that is actually
    signed, allowing comparison with JavaScript canonicalization.
    """
    canonical_dir = fixtures_dir / "canonical"
    canonical_dir.mkdir(parents=True, exist_ok=True)

    for vc_file in sorted(vcs_dir.glob("*.json")):
        # Read the VC
        with open(vc_file) as f:
            vc = json.load(f)

        # Remove proof to get the document that was signed
        vc_without_proof = {k: v for k, v in vc.items() if k != "proof"}

        # Canonicalize using Python implementation
        canonical_nquads = canonicalize_document(vc_without_proof)

        # Save the canonical form
        canonical_file = canonical_dir / f"{vc_file.stem}.nquads"
        with open(canonical_file, "w") as f:
            f.write(canonical_nquads)


@pytest.mark.vc_compat
def test_generate_manifest(fixtures_dir: Path, vcs_dir: Path):
    """Generate manifest file listing all fixtures.

    This should run last to collect all generated fixtures.
    """
    manifest = {
        "description": "VC compatibility test fixtures",
        "generated_by": "tests/vc_compat/test_generate_fixtures.py",
        "divisions": ["advisory", "epdw"],
        "did_documents": [],
        "vcs": [],
    }

    # List DID documents
    for did_file in sorted(fixtures_dir.glob("*_did.json")):
        manifest["did_documents"].append({
            "file": did_file.name,
            "division": did_file.stem.replace("_did", ""),
        })

    # List VCs
    for vc_file in sorted(vcs_dir.glob("*.json")):
        # Read the VC to extract metadata
        with open(vc_file) as f:
            vc = json.load(f)

        manifest["vcs"].append({
            "file": f"vcs/{vc_file.name}",
            "issuer": vc.get("issuer", ""),
            "subject_id": vc.get("credentialSubject", {}).get("id", ""),
            "type": vc.get("type", []),
        })

    # Save manifest
    manifest_path = fixtures_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Verify at least some fixtures were generated
    assert len(manifest["did_documents"]) >= 2  # advisory and epdw
    assert len(manifest["vcs"]) >= 5  # At least 5 test VCs
