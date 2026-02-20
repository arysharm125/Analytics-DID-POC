"""Unit tests for app/did_utils/jsonld.py JSON-LD utilities."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.did_utils.jsonld import (
    _get_contexts_path,
    _load_context,
    _load_all_contexts,
    _custom_document_loader,
    _context_cache,
    _CONTEXT_FILES,
    VC_CONTEXTS,
    DATA_INTEGRITY_V2_CONTEXT,
    canonicalize_document,
    _document_to_messages,
    prepare_vc_for_signing,
    prepare_vp_for_signing,
    create_proof_options,
    proof_options_to_messages,
    DigitalArtefactVCInput,
    generate_digital_artefact_vc,
)
from app.routers.basetypes import (
    did_from_uuid,
    division_did_from_division,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def clear_context_cache():
    """Clear the context cache before and after each test."""
    _context_cache.clear()
    yield
    _context_cache.clear()


@pytest.fixture
def sample_uuid() -> str:
    """A valid UUID string for testing."""
    return "12345678-1234-1234-1234-123456789abc"


@pytest.fixture
def sample_uuid_2() -> str:
    """Another valid UUID string for testing."""
    return "87654321-4321-4321-4321-cba987654321"


@pytest.fixture
def sample_version_uid() -> str:
    """A valid version UUID string for testing."""
    return "abcdef12-abcd-abcd-abcd-abcdef123456"


@pytest.fixture
def sample_multihash() -> str:
    """A valid SHA-256 multihash for testing."""
    return "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"


@pytest.fixture
def sample_vc() -> dict:
    """A minimal valid VC for testing."""
    return {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://did.amd.com/contexts/digitalArtefacts/v1",
        ],
        "type": ["VerifiableCredential", "DigitalArtefactCredential"],
        "issuer": "did:web:did.amd.com:epdw",
        "issuanceDate": "2024-01-01T00:00:00+00:00",
        "credentialSubject": {
            "id": "did:web:did.amd.com:12345678-1234-1234-1234-123456789abc",
            "version": 1,
            "versionUid": "did:web:did.amd.com:abcdef12-abcd-abcd-abcd-abcdef123456",
            "creationDate": "2024-01-01T00:00:00+00:00",
        }
    }


@pytest.fixture
def sample_vc_with_proof(sample_vc) -> dict:
    """A VC with a proof for testing removal."""
    vc = sample_vc.copy()
    vc["proof"] = {
        "type": "DataIntegrityProof",
        "cryptosuite": "eddsa-rdfc-2022",
        "created": "2024-01-01T00:00:00+00:00",
        "verificationMethod": "did:web:did.amd.com:epdw#key-1",
        "proofPurpose": "assertionMethod",
        "proofValue": "z58DAdFfa9SkqZMVPxAQpic7ndTeel..."
    }
    return vc


@pytest.fixture
def sample_vp(sample_vc_with_proof) -> dict:
    """A minimal VP with embedded VC for testing."""
    return {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
        ],
        "type": ["VerifiablePresentation"],
        "holder": "did:web:did.amd.com:holder123",
        "verifiableCredential": [sample_vc_with_proof],
        "proof": {
            "type": "DataIntegrityProof",
            "cryptosuite": "eddsa-rdfc-2022",
            "created": "2024-01-01T00:00:00+00:00",
            "verificationMethod": "did:web:did.amd.com:epdw#key-1",
            "proofPurpose": "authentication",
            "proofValue": "z58DAdFfa9SkqZMVPxAQpic7ndTeel..."
        }
    }


@pytest.fixture
def sample_digital_artefact_input(
    sample_uuid,
    sample_version_uid,
    sample_multihash,
) -> DigitalArtefactVCInput:
    """A valid DigitalArtefactVCInput for testing."""
    return DigitalArtefactVCInput(
        uid=sample_uuid,
        version=1,
        version_uid=sample_version_uid,
        hash=sample_multihash,
        metadata={"key": "value"},
        created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        division="epdw",
        provenance=[did_from_uuid(sample_uuid)],
    )


@pytest.fixture
def sample_digital_artefact_input_minimal(
    sample_uuid,
    sample_version_uid,
) -> DigitalArtefactVCInput:
    """A minimal DigitalArtefactVCInput without optional fields."""
    return DigitalArtefactVCInput(
        uid=sample_uuid,
        version=1,
        version_uid=sample_version_uid,
        hash=None,
        metadata=None,
        created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        division="advisory",
        provenance=None,
    )


# =============================================================================
# TestContextLoading
# =============================================================================

class TestContextLoading:
    """Tests for context file loading functions."""

    def test_get_contexts_path_returns_correct_directory(self):
        """Verify _get_contexts_path returns the contexts directory."""
        path = _get_contexts_path()
        assert isinstance(path, Path)
        assert path.name == "contexts"
        assert path.parent.name == "did_utils"

    def test_load_context_returns_cached_context(self, clear_context_cache):
        """Verify caching behavior when loading same URL twice."""
        url = "https://www.w3.org/2018/credentials/v1"

        # First load
        context1 = _load_context(url)
        assert context1 is not None

        # Verify it's cached
        assert url in _context_cache

        # Second load should return same object
        context2 = _load_context(url)
        assert context2 is context1

    def test_load_context_returns_none_for_unknown_url(self, clear_context_cache):
        """Verify _load_context returns None for unmapped URLs."""
        result = _load_context("https://unknown.example.com/context")
        assert result is None

    def test_load_context_loads_valid_context_file(self, clear_context_cache):
        """Verify loading a known context URL returns dict with @context."""
        url = "https://www.w3.org/2018/credentials/v1"
        context = _load_context(url)

        assert context is not None
        assert isinstance(context, dict)
        assert "@context" in context

    def test_load_all_contexts_loads_all_mapped_contexts(self, clear_context_cache):
        """Verify _load_all_contexts loads all 4 mapped contexts."""
        contexts = _load_all_contexts()

        assert len(contexts) == len(_CONTEXT_FILES)
        for url in _CONTEXT_FILES:
            assert url in contexts
            assert isinstance(contexts[url], dict)

    def test_vc_contexts_global_is_populated(self):
        """Verify VC_CONTEXTS module-level dict is populated."""
        assert isinstance(VC_CONTEXTS, dict)
        assert len(VC_CONTEXTS) > 0
        assert "https://www.w3.org/2018/credentials/v1" in VC_CONTEXTS


# =============================================================================
# TestCustomDocumentLoader
# =============================================================================

class TestCustomDocumentLoader:
    """Tests for custom JSON-LD document loader."""

    def test_custom_document_loader_returns_local_context(self, clear_context_cache):
        """Verify local contexts are loaded for known URLs."""
        url = "https://www.w3.org/2018/credentials/v1"
        result = _custom_document_loader(url)

        assert result is not None
        assert "document" in result
        assert "@context" in result["document"]

    def test_custom_document_loader_response_format(self, clear_context_cache):
        """Verify response has correct keys."""
        url = "https://www.w3.org/2018/credentials/v1"
        result = _custom_document_loader(url)

        assert "contentType" in result
        assert result["contentType"] == "application/ld+json"
        assert "contextUrl" in result
        assert result["contextUrl"] is None
        assert "document" in result
        assert "documentUrl" in result
        assert result["documentUrl"] == url

    def test_custom_document_loader_falls_back_for_unknown_url(self, clear_context_cache):
        """Verify fallback behavior for unknown URLs."""
        url = "https://example.com/unknown-context"

        # Mock the fallback loader to avoid network calls
        with patch("app.did_utils.jsonld.jsonld.load_document") as mock_loader:
            mock_loader.return_value = {
                "contentType": "application/ld+json",
                "contextUrl": None,
                "document": {"@context": {}},
                "documentUrl": url,
            }

            result = _custom_document_loader(url)

            mock_loader.assert_called_once_with(url, None)
            assert result["documentUrl"] == url


# =============================================================================
# TestCanonicalizeDocument
# =============================================================================

class TestCanonicalizeDocument:
    """Tests for N-Quads canonicalization."""

    def test_canonicalize_simple_vc(self, sample_vc):
        """Verify a simple VC converts to N-Quads string."""
        result = canonicalize_document(sample_vc)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_canonicalize_returns_string(self, sample_vc):
        """Verify return type is str."""
        result = canonicalize_document(sample_vc)
        assert isinstance(result, str)

    def test_canonicalize_deterministic(self, sample_vc):
        """Verify same document produces same output."""
        result1 = canonicalize_document(sample_vc)
        result2 = canonicalize_document(sample_vc)

        assert result1 == result2

    def test_canonicalize_different_documents_produce_different_output(self, sample_vc):
        """Verify different inputs produce different N-Quads."""
        modified_vc = sample_vc.copy()
        modified_vc["issuanceDate"] = "2025-01-01T00:00:00+00:00"

        result1 = canonicalize_document(sample_vc)
        result2 = canonicalize_document(modified_vc)

        assert result1 != result2


# =============================================================================
# TestDocumentToMessages
# =============================================================================

class TestDocumentToMessages:
    """Tests for N-Quad statement splitting."""

    def test_document_to_messages_returns_list(self, sample_vc):
        """Verify return type is list[str]."""
        result = _document_to_messages(sample_vc)

        assert isinstance(result, list)
        assert all(isinstance(item, str) for item in result)

    def test_document_to_messages_filters_empty_lines(self, sample_vc):
        """Verify empty lines are filtered out."""
        result = _document_to_messages(sample_vc)

        assert all(len(stmt) > 0 for stmt in result)

    def test_document_to_messages_strips_whitespace(self, sample_vc):
        """Verify statements are stripped."""
        result = _document_to_messages(sample_vc)

        for stmt in result:
            assert stmt == stmt.strip()


# =============================================================================
# TestPrepareVCForSigning
# =============================================================================

class TestPrepareVCForSigning:
    """Tests for VC preparation."""

    def test_prepare_vc_removes_proof(self, sample_vc_with_proof):
        """Verify proof key is removed from output."""
        vc_without_proof, _ = prepare_vc_for_signing(sample_vc_with_proof)

        assert "proof" not in vc_without_proof

    def test_prepare_vc_preserves_other_fields(self, sample_vc_with_proof):
        """Verify non-proof fields are preserved."""
        vc_without_proof, _ = prepare_vc_for_signing(sample_vc_with_proof)

        assert "issuer" in vc_without_proof
        assert vc_without_proof["issuer"] == sample_vc_with_proof["issuer"]
        assert "credentialSubject" in vc_without_proof
        assert vc_without_proof["credentialSubject"] == sample_vc_with_proof["credentialSubject"]

    def test_prepare_vc_adds_data_integrity_context_if_missing(self, sample_vc):
        """Verify DI v2 context is added when not present."""
        assert DATA_INTEGRITY_V2_CONTEXT not in sample_vc["@context"]

        vc_without_proof, _ = prepare_vc_for_signing(sample_vc)

        assert DATA_INTEGRITY_V2_CONTEXT in vc_without_proof["@context"]

    def test_prepare_vc_keeps_data_integrity_context_if_present(self):
        """Verify DI v2 context is not duplicated."""
        vc = {
            "@context": [
                "https://www.w3.org/2018/credentials/v1",
                DATA_INTEGRITY_V2_CONTEXT,
            ],
            "type": ["VerifiableCredential"],
            "issuer": "did:web:did.amd.com:epdw",
            "credentialSubject": {"id": "did:web:did.amd.com:test"},
        }

        vc_without_proof, _ = prepare_vc_for_signing(vc)

        # Count occurrences of DATA_INTEGRITY_V2_CONTEXT
        count = vc_without_proof["@context"].count(DATA_INTEGRITY_V2_CONTEXT)
        assert count == 1

    def test_prepare_vc_handles_string_context(self):
        """Verify single string @context is converted to list."""
        vc = {
            "@context": "https://www.w3.org/2018/credentials/v1",
            "type": ["VerifiableCredential"],
            "issuer": "did:web:did.amd.com:epdw",
            "credentialSubject": {"id": "did:web:did.amd.com:test"},
        }

        vc_without_proof, _ = prepare_vc_for_signing(vc)

        assert isinstance(vc_without_proof["@context"], list)
        assert "https://www.w3.org/2018/credentials/v1" in vc_without_proof["@context"]
        assert DATA_INTEGRITY_V2_CONTEXT in vc_without_proof["@context"]

    def test_prepare_vc_returns_tuple(self, sample_vc):
        """Verify return type is tuple of (dict, list[str])."""
        result = prepare_vc_for_signing(sample_vc)

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], dict)
        assert isinstance(result[1], list)

    def test_prepare_vc_returns_nquad_messages(self, sample_vc):
        """Verify messages list contains valid N-Quad strings."""
        _, messages = prepare_vc_for_signing(sample_vc)

        assert len(messages) > 0
        for msg in messages:
            assert isinstance(msg, str)
            assert len(msg) > 0


# =============================================================================
# TestPrepareVPForSigning
# =============================================================================

class TestPrepareVPForSigning:
    """Tests for VP preparation."""

    def test_prepare_vp_removes_vp_level_proof(self, sample_vp):
        """Verify VP-level proof is removed."""
        vp_without_proof, _ = prepare_vp_for_signing(sample_vp)

        assert "proof" not in vp_without_proof

    def test_prepare_vp_preserves_vc_proofs(self, sample_vp):
        """Verify embedded VC proofs are kept."""
        vp_without_proof, _ = prepare_vp_for_signing(sample_vp)

        # The embedded VC should still have its proof
        embedded_vc = vp_without_proof["verifiableCredential"][0]
        assert "proof" in embedded_vc

    def test_prepare_vp_adds_data_integrity_context(self, sample_vp):
        """Verify DI v2 context is added."""
        assert DATA_INTEGRITY_V2_CONTEXT not in sample_vp["@context"]

        vp_without_proof, _ = prepare_vp_for_signing(sample_vp)

        assert DATA_INTEGRITY_V2_CONTEXT in vp_without_proof["@context"]

    def test_prepare_vp_handles_string_context(self):
        """Verify single string @context is converted to list."""
        vp = {
            "@context": "https://www.w3.org/2018/credentials/v1",
            "type": ["VerifiablePresentation"],
            "holder": "did:web:did.amd.com:holder",
            "verifiableCredential": [],
        }

        vp_without_proof, _ = prepare_vp_for_signing(vp)

        assert isinstance(vp_without_proof["@context"], list)


# =============================================================================
# TestCreateProofOptions
# =============================================================================

class TestCreateProofOptions:
    """Tests for proof options generation."""

    def test_create_proof_options_structure(self):
        """Verify returned dict has all required keys."""
        verification_method = "did:web:did.amd.com:epdw#key-1"
        result = create_proof_options(verification_method)

        assert "@context" in result
        assert "type" in result
        assert "cryptosuite" in result
        assert "created" in result
        assert "verificationMethod" in result
        assert "proofPurpose" in result

    def test_create_proof_options_default_values(self):
        """Verify defaults: assertionMethod, eddsa-rdfc-2022."""
        verification_method = "did:web:did.amd.com:epdw#key-1"
        result = create_proof_options(verification_method)

        assert result["proofPurpose"] == "assertionMethod"
        assert result["cryptosuite"] == "eddsa-rdfc-2022"

    def test_create_proof_options_custom_values(self):
        """Verify custom proof_purpose, cryptosuite are used."""
        verification_method = "did:web:did.amd.com:epdw#key-1"
        result = create_proof_options(
            verification_method,
            proof_purpose="authentication",
            cryptosuite="custom-suite",
        )

        assert result["proofPurpose"] == "authentication"
        assert result["cryptosuite"] == "custom-suite"

    def test_create_proof_options_generated_timestamp(self):
        """Verify created is auto-generated if not provided."""
        verification_method = "did:web:did.amd.com:epdw#key-1"
        result = create_proof_options(verification_method)

        assert "created" in result
        # Should be a valid ISO 8601 timestamp
        datetime.fromisoformat(result["created"])

    def test_create_proof_options_provided_timestamp(self):
        """Verify provided created is used."""
        verification_method = "did:web:did.amd.com:epdw#key-1"
        timestamp = "2024-01-01T00:00:00+00:00"
        result = create_proof_options(verification_method, created=timestamp)

        assert result["created"] == timestamp

    def test_create_proof_options_includes_di_context(self):
        """Verify @context is DATA_INTEGRITY_V2_CONTEXT."""
        verification_method = "did:web:did.amd.com:epdw#key-1"
        result = create_proof_options(verification_method)

        assert result["@context"] == DATA_INTEGRITY_V2_CONTEXT

    def test_create_proof_options_type_is_data_integrity_proof(self):
        """Verify type is DataIntegrityProof."""
        verification_method = "did:web:did.amd.com:epdw#key-1"
        result = create_proof_options(verification_method)

        assert result["type"] == "DataIntegrityProof"


# =============================================================================
# TestProofOptionsToMessages
# =============================================================================

class TestProofOptionsToMessages:
    """Tests for proof options canonicalization."""

    def test_proof_options_to_messages_returns_list(self):
        """Verify return type is list[str]."""
        proof_options = create_proof_options(
            "did:web:did.amd.com:epdw#key-1",
            created="2024-01-01T00:00:00+00:00",
        )
        result = proof_options_to_messages(proof_options)

        assert isinstance(result, list)
        assert all(isinstance(item, str) for item in result)

    def test_proof_options_to_messages_canonical(self):
        """Verify output is deterministic."""
        proof_options = create_proof_options(
            "did:web:did.amd.com:epdw#key-1",
            created="2024-01-01T00:00:00+00:00",
        )

        result1 = proof_options_to_messages(proof_options)
        result2 = proof_options_to_messages(proof_options)

        assert result1 == result2


# =============================================================================
# TestDigitalArtefactVCInput
# =============================================================================

class TestDigitalArtefactVCInput:
    """Tests for DigitalArtefactVCInput dataclass."""

    def test_digital_artefact_vc_input_creation(
        self,
        sample_uuid,
        sample_version_uid,
        sample_multihash,
    ):
        """Verify dataclass can be instantiated with valid data."""
        input_data = DigitalArtefactVCInput(
            uid=sample_uuid,
            version=1,
            version_uid=sample_version_uid,
            hash=sample_multihash,
            metadata={"key": "value"},
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            division="epdw",
            provenance=[did_from_uuid(sample_uuid)],
        )

        assert input_data.uid == sample_uuid
        assert input_data.version == 1
        assert input_data.version_uid == sample_version_uid
        assert input_data.hash == sample_multihash
        assert input_data.metadata == {"key": "value"}
        assert input_data.division == "epdw"

    def test_digital_artefact_vc_input_optional_fields(
        self,
        sample_uuid,
        sample_version_uid,
    ):
        """Verify optional fields (hash, metadata, provenance) can be None."""
        input_data = DigitalArtefactVCInput(
            uid=sample_uuid,
            version=1,
            version_uid=sample_version_uid,
            hash=None,
            metadata=None,
            created_at=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
            division="epdw",
            provenance=None,
        )

        assert input_data.hash is None
        assert input_data.metadata is None
        assert input_data.provenance is None


# =============================================================================
# TestGenerateDigitalArtefactVC
# =============================================================================

class TestGenerateDigitalArtefactVC:
    """Tests for VC generation."""

    def test_generate_vc_format_1_structure(self, sample_digital_artefact_input):
        """Verify format 1 VC has correct structure."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        assert "@context" in vc
        assert "type" in vc
        assert "issuer" in vc
        assert "issuanceDate" in vc
        assert "credentialSubject" in vc

    def test_generate_vc_contexts(self, sample_digital_artefact_input):
        """Verify @context includes all 3 required contexts."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        contexts = vc["@context"]
        assert "https://www.w3.org/2018/credentials/v1" in contexts
        assert "https://did.amd.com/contexts/digitalArtefacts/v1" in contexts
        assert DATA_INTEGRITY_V2_CONTEXT in contexts

    def test_generate_vc_types(self, sample_digital_artefact_input):
        """Verify type includes VerifiableCredential and DigitalArtefactCredential."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        assert "VerifiableCredential" in vc["type"]
        assert "DigitalArtefactCredential" in vc["type"]

    def test_generate_vc_issuer_is_division_did(self, sample_digital_artefact_input):
        """Verify issuer is correct division DID."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        expected_issuer = division_did_from_division(sample_digital_artefact_input.division)
        assert vc["issuer"] == expected_issuer

    def test_generate_vc_credential_subject_id(self, sample_digital_artefact_input):
        """Verify credentialSubject.id is correct DID from UUID."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        expected_id = did_from_uuid(sample_digital_artefact_input.uid)
        assert vc["credentialSubject"]["id"] == expected_id

    def test_generate_vc_credential_subject_version(self, sample_digital_artefact_input):
        """Verify version field is set."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        assert vc["credentialSubject"]["version"] == sample_digital_artefact_input.version

    def test_generate_vc_credential_subject_version_uid(self, sample_digital_artefact_input):
        """Verify versionUid is correct DID."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        expected_version_uid = did_from_uuid(sample_digital_artefact_input.version_uid)
        assert vc["credentialSubject"]["versionUid"] == expected_version_uid

    def test_generate_vc_with_hash(self, sample_digital_artefact_input):
        """Verify artefactHash is included when hash is provided."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        assert "artefactHash" in vc["credentialSubject"]
        assert vc["credentialSubject"]["artefactHash"] == str(sample_digital_artefact_input.hash)

    def test_generate_vc_without_hash(self, sample_digital_artefact_input_minimal):
        """Verify artefactHash is omitted when hash is None."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input_minimal, issuance_date)

        assert "artefactHash" not in vc["credentialSubject"]

    def test_generate_vc_with_metadata(self, sample_digital_artefact_input):
        """Verify artefactMetadata is included when provided."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        assert "artefactMetadata" in vc["credentialSubject"]
        assert vc["credentialSubject"]["artefactMetadata"] == sample_digital_artefact_input.metadata

    def test_generate_vc_without_metadata(self, sample_digital_artefact_input_minimal):
        """Verify artefactMetadata is omitted when None."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input_minimal, issuance_date)

        assert "artefactMetadata" not in vc["credentialSubject"]

    def test_generate_vc_with_provenance(self, sample_digital_artefact_input):
        """Verify provenance is included as DID list."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        assert "provenance" in vc["credentialSubject"]
        assert isinstance(vc["credentialSubject"]["provenance"], list)

    def test_generate_vc_without_provenance(self, sample_digital_artefact_input_minimal):
        """Verify provenance is omitted when None."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input_minimal, issuance_date)

        assert "provenance" not in vc["credentialSubject"]

    def test_generate_vc_unsupported_format_raises(self, sample_digital_artefact_input):
        """Verify format != 1 raises RuntimeError."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        with pytest.raises(RuntimeError, match="Only format 1"):
            generate_digital_artefact_vc(2, sample_digital_artefact_input, issuance_date)

        with pytest.raises(RuntimeError, match="Only format 1"):
            generate_digital_artefact_vc(0, sample_digital_artefact_input, issuance_date)

    def test_generate_vc_issuance_date_format(self, sample_digital_artefact_input):
        """Verify issuanceDate is ISO 8601 format."""
        issuance_date = datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        assert vc["issuanceDate"] == issuance_date.isoformat()
        # Should be parseable
        datetime.fromisoformat(vc["issuanceDate"])

    def test_generate_vc_creation_date_format(self, sample_digital_artefact_input):
        """Verify creationDate is ISO 8601 format."""
        issuance_date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        vc = generate_digital_artefact_vc(1, sample_digital_artefact_input, issuance_date)

        creation_date_str = vc["credentialSubject"]["creationDate"]
        # Should be parseable
        datetime.fromisoformat(creation_date_str)
        assert creation_date_str == sample_digital_artefact_input.created_at.isoformat()
