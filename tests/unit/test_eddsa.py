"""Unit tests for app/did_utils/eddsa.py EdDSA signature utilities."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from nacl.signing import SigningKey

from app.did_utils.eddsa import (
    EDDSA_RDFC_2022_CRYPTOSUITE,
    MULTIBASE_BASE58BTC_PREFIX,
    MULTIBASE_BASE64URL_PREFIX,
    MULTICODEC_ED25519_PUB,
    _create_verify_data,
    create_keypair_from_hex,
    decode_multibase_base64url,
    encode_multibase_base64url,
    get_public_key_bytes,
    get_public_key_multibase,
    secure_clear_signing_key,
    secure_signing_context,
    sign_data,
    sign_vc,
    sign_vp,
    sodium_memzero,
    verify_signature,
    verify_vc_signature,
    verify_vp_signature,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def signed_vc(sample_vc, signing_key) -> dict:
    """A signed VC for testing verification."""
    verification_method = "did:web:did.amd.com:epdw#key-1"
    created = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    return sign_vc(sample_vc, signing_key, verification_method, created)


# =============================================================================
# TestMultibaseEncoding
# =============================================================================

class TestMultibaseEncoding:
    """Tests for multibase base64url encoding/decoding."""

    def test_encode_multibase_base64url_valid_bytes(self):
        """Valid bytes should be encoded as multibase base64url string."""
        data = b"Hello, World!"
        result = encode_multibase_base64url(data)

        assert isinstance(result, str)
        assert result.startswith(MULTIBASE_BASE64URL_PREFIX)

    def test_encode_multibase_base64url_empty_bytes(self):
        """Empty bytes should encode to 'u' prefix only."""
        data = b""
        result = encode_multibase_base64url(data)

        assert result == MULTIBASE_BASE64URL_PREFIX

    def test_encode_multibase_base64url_no_padding(self):
        """Encoded string should not contain padding characters."""
        data = b"test"
        result = encode_multibase_base64url(data)

        assert "=" not in result

    def test_decode_multibase_base64url_valid_string(self):
        """Valid multibase string should decode to bytes."""
        original = b"Hello, World!"
        encoded = encode_multibase_base64url(original)
        decoded = decode_multibase_base64url(encoded)

        assert decoded == original

    def test_decode_multibase_base64url_wrong_prefix_raises(self):
        """String with wrong prefix should raise ValueError."""
        with pytest.raises(ValueError, match="Expected multibase prefix"):
            decode_multibase_base64url("zInvalidPrefix")

    def test_decode_multibase_base64url_empty_content(self):
        """Multibase string with only prefix should decode to empty bytes."""
        result = decode_multibase_base64url(MULTIBASE_BASE64URL_PREFIX)
        assert result == b""

    def test_decode_multibase_base64url_handles_padding(self):
        """Decoder should handle missing padding correctly."""
        # Create encoded string without padding
        data = b"test"
        encoded = encode_multibase_base64url(data)
        decoded = decode_multibase_base64url(encoded)

        assert decoded == data

    def test_encode_decode_roundtrip(self):
        """Encoding then decoding should return original bytes."""
        test_cases = [
            b"a",
            b"ab",
            b"abc",
            b"abcd",
            b"Hello, World!",
            b"\x00\x01\x02\x03\xff",
            b"x" * 64,  # Ed25519 signature length
        ]

        for data in test_cases:
            encoded = encode_multibase_base64url(data)
            decoded = decode_multibase_base64url(encoded)
            assert decoded == data, f"Roundtrip failed for {data!r}"


# =============================================================================
# TestKeypairCreation
# =============================================================================

class TestKeypairCreation:
    """Tests for Ed25519 keypair creation from hex seed."""

    def test_create_keypair_from_valid_hex(self, sample_secret_key_hex):
        """Valid 32-byte hex string should create SigningKey."""
        key = create_keypair_from_hex(sample_secret_key_hex)

        assert isinstance(key, SigningKey)

    def test_create_keypair_from_hex_deterministic(self, sample_secret_key_hex):
        """Same hex seed should produce same public key."""
        key1 = create_keypair_from_hex(sample_secret_key_hex)
        key2 = create_keypair_from_hex(sample_secret_key_hex)

        assert bytes(key1.verify_key) == bytes(key2.verify_key)

    def test_create_keypair_invalid_hex_raises(self):
        """Invalid hex string should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid hex string"):
            create_keypair_from_hex("not-hex-string")

    def test_create_keypair_wrong_length_short_raises(self):
        """Hex string shorter than 32 bytes should raise ValueError."""
        short_hex = "a" * 62  # 31 bytes

        with pytest.raises(ValueError, match="must be 32 bytes"):
            create_keypair_from_hex(short_hex)

    def test_create_keypair_wrong_length_long_raises(self):
        """Hex string longer than 32 bytes should raise ValueError."""
        long_hex = "a" * 66  # 33 bytes

        with pytest.raises(ValueError, match="must be 32 bytes"):
            create_keypair_from_hex(long_hex)

    def test_create_keypair_empty_string_raises(self):
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError, match="must be 32 bytes"):
            create_keypair_from_hex("")


# =============================================================================
# TestPublicKeyExport
# =============================================================================

class TestPublicKeyExport:
    """Tests for public key export functions."""

    def test_get_public_key_multibase_format(self, signing_key):
        """Public key multibase should be z-prefixed base58btc string."""
        result = get_public_key_multibase(signing_key)

        assert isinstance(result, str)
        assert result.startswith(MULTIBASE_BASE58BTC_PREFIX)

    def test_get_public_key_multibase_includes_multicodec_prefix(self, signing_key):
        """Multibase string should decode to include Ed25519 multicodec prefix."""
        import base58

        result = get_public_key_multibase(signing_key)
        # Remove 'z' prefix and decode
        decoded = base58.b58decode(result[1:])

        # First two bytes should be Ed25519 multicodec prefix
        assert decoded[:2] == MULTICODEC_ED25519_PUB

    def test_get_public_key_multibase_deterministic(self, signing_key):
        """Same signing key should produce same multibase string."""
        result1 = get_public_key_multibase(signing_key)
        result2 = get_public_key_multibase(signing_key)

        assert result1 == result2

    def test_get_public_key_bytes_returns_32_bytes(self, signing_key):
        """Public key bytes should be exactly 32 bytes."""
        result = get_public_key_bytes(signing_key)

        assert isinstance(result, bytes)
        assert len(result) == 32

    def test_get_public_key_bytes_deterministic(self, signing_key):
        """Same signing key should produce same bytes."""
        result1 = get_public_key_bytes(signing_key)
        result2 = get_public_key_bytes(signing_key)

        assert result1 == result2

    def test_get_public_key_bytes_matches_verify_key(self, signing_key):
        """Public key bytes should match verify_key bytes."""
        result = get_public_key_bytes(signing_key)
        expected = bytes(signing_key.verify_key)

        assert result == expected


# =============================================================================
# TestSigningAndVerification
# =============================================================================

class TestSigningAndVerification:
    """Tests for sign_data and verify_signature functions."""

    def test_sign_data_returns_64_bytes(self, signing_key):
        """Ed25519 signature should be exactly 64 bytes."""
        data = b"test message"
        signature = sign_data(signing_key, data)

        assert isinstance(signature, bytes)
        assert len(signature) == 64

    def test_sign_data_deterministic(self, signing_key):
        """Same data should produce same signature."""
        data = b"test message"

        sig1 = sign_data(signing_key, data)
        sig2 = sign_data(signing_key, data)

        assert sig1 == sig2

    def test_sign_data_different_data_different_signature(self, signing_key):
        """Different data should produce different signatures."""
        sig1 = sign_data(signing_key, b"message 1")
        sig2 = sign_data(signing_key, b"message 2")

        assert sig1 != sig2

    def test_sign_data_empty_data(self, signing_key):
        """Empty data should be signable."""
        signature = sign_data(signing_key, b"")

        assert len(signature) == 64

    def test_verify_signature_valid_signature_returns_true(self, signing_key):
        """Valid signature should verify successfully."""
        data = b"test message"
        signature = sign_data(signing_key, data)
        public_key = get_public_key_bytes(signing_key)

        result = verify_signature(public_key, data, signature)

        assert result is True

    def test_verify_signature_tampered_data_returns_false(self, signing_key):
        """Signature should fail if data is modified."""
        data = b"test message"
        signature = sign_data(signing_key, data)
        public_key = get_public_key_bytes(signing_key)

        tampered_data = b"tampered message"
        result = verify_signature(public_key, tampered_data, signature)

        assert result is False

    def test_verify_signature_wrong_key_returns_false(self, signing_key):
        """Signature should fail with wrong public key."""
        data = b"test message"
        signature = sign_data(signing_key, data)

        # Create different key
        wrong_key = create_keypair_from_hex("b" * 64)
        wrong_public = get_public_key_bytes(wrong_key)

        result = verify_signature(wrong_public, data, signature)

        assert result is False

    def test_verify_signature_wrong_signature_returns_false(self, signing_key):
        """Wrong signature should fail verification."""
        data = b"test message"
        public_key = get_public_key_bytes(signing_key)

        # Create wrong signature
        wrong_signature = b"x" * 64

        result = verify_signature(public_key, data, wrong_signature)

        assert result is False

    def test_verify_signature_invalid_signature_length_returns_false(self, signing_key):
        """Signature with wrong length should return False."""
        data = b"test message"
        public_key = get_public_key_bytes(signing_key)

        # Wrong length signature
        bad_signature = b"x" * 32

        result = verify_signature(public_key, data, bad_signature)

        assert result is False


# =============================================================================
# TestSecureMemory
# =============================================================================

class TestSecureMemory:
    """Tests for secure memory clearing functions."""

    def test_sodium_memzero_empty_buffer_no_error(self):
        """Empty buffer should be handled without error."""
        buffer = b""
        sodium_memzero(buffer)  # Should not raise

    def test_sodium_memzero_bytes_buffer(self):
        """Bytes buffer should be zeroed (best effort)."""
        buffer = bytearray(b"secret")
        original_len = len(buffer)

        sodium_memzero(buffer)

        # Buffer length should remain the same
        assert len(buffer) == original_len

    def test_sodium_memzero_bytearray_buffer(self):
        """Bytearray buffer should be zeroed."""
        buffer = bytearray(b"secret")

        sodium_memzero(buffer)

        # Buffer should be all zeros
        assert buffer == bytearray(b"\x00" * len(buffer))

    def test_secure_clear_signing_key_no_exception(self, signing_key):
        """Clearing signing key should not raise exception."""
        secure_clear_signing_key(signing_key)  # Should not raise

    def test_secure_clear_signing_key_with_gc_trigger(self, signing_key):
        """gc trigger parameter should work."""
        secure_clear_signing_key(signing_key, trigger_gc=True)  # Should not raise
        secure_clear_signing_key(signing_key, trigger_gc=False)  # Should not raise


# =============================================================================
# TestSecureSigningContext
# =============================================================================

class TestSecureSigningContext:
    """Tests for secure_signing_context context manager."""

    def test_secure_signing_context_yields_key(self, signing_key):
        """Context manager should yield the signing key."""
        with secure_signing_context(signing_key) as key:
            assert key is signing_key

    def test_secure_signing_context_clears_on_normal_exit(self, signing_key):
        """Key should be cleared after normal context exit."""
        with patch("app.did_utils.eddsa.secure_clear_signing_key") as mock_clear:
            with secure_signing_context(signing_key):
                pass

            mock_clear.assert_called_once_with(signing_key)

    def test_secure_signing_context_clears_on_exception(self, signing_key):
        """Key should be cleared even when exception occurs."""
        with patch("app.did_utils.eddsa.secure_clear_signing_key") as mock_clear:
            try:
                with secure_signing_context(signing_key):
                    raise RuntimeError("Test error")
            except RuntimeError:
                pass

            mock_clear.assert_called_once_with(signing_key)

    def test_secure_signing_context_allows_signing(self, signing_key):
        """Signing should work within context."""
        data = b"test message"

        with secure_signing_context(signing_key) as key:
            signature = sign_data(key, data)

        assert len(signature) == 64


# =============================================================================
# TestCreateVerifyData
# =============================================================================

class TestCreateVerifyData:
    """Tests for _create_verify_data internal function."""

    def test_create_verify_data_returns_bytes(self, sample_vc):
        """Verify data should be bytes."""
        from app.did_utils.jsonld import create_proof_options

        proof_options = create_proof_options(
            verification_method="did:web:did.amd.com:epdw#key-1",
            created="2024-01-01T00:00:00+00:00",
        )

        result = _create_verify_data(sample_vc, proof_options)

        assert isinstance(result, bytes)

    def test_create_verify_data_length(self, sample_vc):
        """Verify data should be 64 bytes (two SHA-256 hashes)."""
        from app.did_utils.jsonld import create_proof_options

        proof_options = create_proof_options(
            verification_method="did:web:did.amd.com:epdw#key-1",
            created="2024-01-01T00:00:00+00:00",
        )

        result = _create_verify_data(sample_vc, proof_options)

        # SHA-256 hash is 32 bytes, concatenation of two = 64 bytes
        assert len(result) == 64

    def test_create_verify_data_deterministic(self, sample_vc):
        """Same inputs should produce same verify data."""
        from app.did_utils.jsonld import create_proof_options

        proof_options = create_proof_options(
            verification_method="did:web:did.amd.com:epdw#key-1",
            created="2024-01-01T00:00:00+00:00",
        )

        result1 = _create_verify_data(sample_vc, proof_options)
        result2 = _create_verify_data(sample_vc, proof_options)

        assert result1 == result2

    def test_create_verify_data_different_document_different_result(self, sample_vc):
        """Different documents should produce different verify data."""
        from app.did_utils.jsonld import create_proof_options

        proof_options = create_proof_options(
            verification_method="did:web:did.amd.com:epdw#key-1",
            created="2024-01-01T00:00:00+00:00",
        )

        modified_vc = sample_vc.copy()
        modified_vc["issuanceDate"] = "2025-01-01T00:00:00+00:00"

        result1 = _create_verify_data(sample_vc, proof_options)
        result2 = _create_verify_data(modified_vc, proof_options)

        assert result1 != result2


# =============================================================================
# TestSignVC
# =============================================================================

class TestSignVC:
    """Tests for sign_vc function."""

    def test_sign_vc_adds_proof(self, sample_vc, signing_key):
        """Signed VC should have proof field."""
        verification_method = "did:web:did.amd.com:epdw#key-1"

        result = sign_vc(sample_vc, signing_key, verification_method)

        assert "proof" in result

    def test_sign_vc_proof_structure(self, sample_vc, signing_key):
        """Proof should have all required fields."""
        verification_method = "did:web:did.amd.com:epdw#key-1"

        result = sign_vc(sample_vc, signing_key, verification_method)
        proof = result["proof"]

        assert proof["type"] == "DataIntegrityProof"
        assert proof["cryptosuite"] == EDDSA_RDFC_2022_CRYPTOSUITE
        assert "created" in proof
        assert proof["verificationMethod"] == verification_method
        assert proof["proofPurpose"] == "assertionMethod"
        assert "proofValue" in proof

    def test_sign_vc_proof_value_is_multibase(self, sample_vc, signing_key):
        """Proof value should be multibase base64url encoded."""
        verification_method = "did:web:did.amd.com:epdw#key-1"

        result = sign_vc(sample_vc, signing_key, verification_method)
        proof_value = result["proof"]["proofValue"]

        assert proof_value.startswith(MULTIBASE_BASE64URL_PREFIX)

    def test_sign_vc_auto_generates_timestamp(self, sample_vc, signing_key):
        """Created timestamp should be auto-generated if not provided."""
        verification_method = "did:web:did.amd.com:epdw#key-1"

        result = sign_vc(sample_vc, signing_key, verification_method)
        created = result["proof"]["created"]

        # Should be a string in ISO format
        assert isinstance(created, str)
        # Should be parseable as datetime
        datetime.fromisoformat(created)

    def test_sign_vc_uses_provided_timestamp(self, sample_vc, signing_key):
        """Provided timestamp should be used."""
        verification_method = "did:web:did.amd.com:epdw#key-1"
        timestamp = datetime(2024, 6, 15, 12, 30, 45, tzinfo=timezone.utc)

        result = sign_vc(sample_vc, signing_key, verification_method, created=timestamp)

        # Created should be converted to ISO format string
        assert result["proof"]["created"] == timestamp.isoformat()

    def test_sign_vc_preserves_original_fields(self, sample_vc, signing_key):
        """Original VC fields should be preserved."""
        verification_method = "did:web:did.amd.com:epdw#key-1"

        result = sign_vc(sample_vc, signing_key, verification_method)

        assert result["issuer"] == sample_vc["issuer"]
        assert result["credentialSubject"] == sample_vc["credentialSubject"]

    def test_sign_vc_removes_existing_proof(self, sample_vc, signing_key):
        """Existing proof should be removed and replaced."""
        vc_with_old_proof = sample_vc.copy()
        vc_with_old_proof["proof"] = {"old": "proof"}

        verification_method = "did:web:did.amd.com:epdw#key-1"
        result = sign_vc(vc_with_old_proof, signing_key, verification_method)

        assert "old" not in result["proof"]
        assert result["proof"]["type"] == "DataIntegrityProof"

    def test_sign_vc_deterministic_with_fixed_timestamp(self, sample_vc, signing_key):
        """Same inputs with fixed timestamp should produce same signature."""
        verification_method = "did:web:did.amd.com:epdw#key-1"
        timestamp = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        result1 = sign_vc(sample_vc, signing_key, verification_method, timestamp)
        result2 = sign_vc(sample_vc, signing_key, verification_method, timestamp)

        assert result1["proof"]["proofValue"] == result2["proof"]["proofValue"]


# =============================================================================
# TestSignVP
# =============================================================================

class TestSignVP:
    """Tests for sign_vp function."""

    def test_sign_vp_adds_proof(self, sample_vp, sample_secret_key_hex):
        """Signed VP should have proof field."""
        verification_method = "did:web:did.amd.com:holder123#key-1"

        result = sign_vp(sample_vp, sample_secret_key_hex, verification_method)

        assert "proof" in result

    def test_sign_vp_proof_structure(self, sample_vp, sample_secret_key_hex):
        """Proof should have all required fields."""
        verification_method = "did:web:did.amd.com:holder123#key-1"

        result = sign_vp(sample_vp, sample_secret_key_hex, verification_method)
        proof = result["proof"]

        assert proof["type"] == "DataIntegrityProof"
        assert proof["cryptosuite"] == EDDSA_RDFC_2022_CRYPTOSUITE
        assert "created" in proof
        assert proof["verificationMethod"] == verification_method
        assert "proofPurpose" in proof
        assert "proofValue" in proof

    def test_sign_vp_default_proof_purpose(self, sample_vp, sample_secret_key_hex):
        """Default proof purpose should be assertionMethod."""
        verification_method = "did:web:did.amd.com:holder123#key-1"

        result = sign_vp(sample_vp, sample_secret_key_hex, verification_method)

        assert result["proof"]["proofPurpose"] == "assertionMethod"

    def test_sign_vp_custom_proof_purpose(self, sample_vp, sample_secret_key_hex):
        """Custom proof purpose should be used."""
        verification_method = "did:web:did.amd.com:holder123#key-1"

        result = sign_vp(
            sample_vp,
            sample_secret_key_hex,
            verification_method,
            proof_purpose="authentication"
        )

        assert result["proof"]["proofPurpose"] == "authentication"

    def test_sign_vp_auto_generates_timestamp(self, sample_vp, sample_secret_key_hex):
        """Created timestamp should be auto-generated if not provided."""
        verification_method = "did:web:did.amd.com:holder123#key-1"

        result = sign_vp(sample_vp, sample_secret_key_hex, verification_method)
        created = result["proof"]["created"]

        # Should be parseable as ISO datetime string
        datetime.fromisoformat(created)

    def test_sign_vp_uses_provided_timestamp(self, sample_vp, sample_secret_key_hex):
        """Provided timestamp should be used."""
        verification_method = "did:web:did.amd.com:holder123#key-1"
        timestamp = "2024-06-15T12:30:45+00:00"

        result = sign_vp(sample_vp, sample_secret_key_hex, verification_method, created=timestamp)

        assert result["proof"]["created"] == timestamp

    def test_sign_vp_preserves_embedded_vc_proofs(self, sample_vp, sample_secret_key_hex):
        """Embedded VC proofs should be preserved."""
        verification_method = "did:web:did.amd.com:holder123#key-1"

        result = sign_vp(sample_vp, sample_secret_key_hex, verification_method)

        # Embedded VC should still have its proof
        embedded_vc = result["verifiableCredential"][0]
        assert "proof" in embedded_vc


# =============================================================================
# TestVerifyVCSignature
# =============================================================================

class TestVerifyVCSignature:
    """Tests for verify_vc_signature function."""

    def test_verify_vc_signature_valid_signature_returns_true(self, signed_vc, signing_key):
        """Valid VC signature should verify successfully."""
        public_key = get_public_key_bytes(signing_key)

        result = verify_vc_signature(signed_vc, public_key)

        assert result is True

    def test_verify_vc_signature_missing_proof_returns_false(self, sample_vc, signing_key):
        """VC without proof should return False."""
        public_key = get_public_key_bytes(signing_key)

        result = verify_vc_signature(sample_vc, public_key)

        assert result is False

    def test_verify_vc_signature_missing_proof_value_returns_false(self, signed_vc, signing_key):
        """VC with proof but no proofValue should return False."""
        public_key = get_public_key_bytes(signing_key)

        vc_no_proof_value = signed_vc.copy()
        vc_no_proof_value["proof"] = {"type": "DataIntegrityProof"}

        result = verify_vc_signature(vc_no_proof_value, public_key)

        assert result is False

    def test_verify_vc_signature_invalid_proof_value_returns_false(self, signed_vc, signing_key):
        """VC with invalid proofValue should return False."""
        public_key = get_public_key_bytes(signing_key)

        vc_bad_proof = signed_vc.copy()
        vc_bad_proof["proof"]["proofValue"] = "znot-valid-multibase"

        result = verify_vc_signature(vc_bad_proof, public_key)

        assert result is False

    def test_verify_vc_signature_wrong_prefix_returns_false(self, signed_vc, signing_key):
        """VC with wrong multibase prefix should return False."""
        public_key = get_public_key_bytes(signing_key)

        vc_wrong_prefix = signed_vc.copy()
        # Use 'z' prefix instead of 'u'
        vc_wrong_prefix["proof"]["proofValue"] = "z" + vc_wrong_prefix["proof"]["proofValue"][1:]

        result = verify_vc_signature(vc_wrong_prefix, public_key)

        assert result is False

    def test_verify_vc_signature_tampered_vc_returns_false(self, signed_vc, signing_key):
        """VC with modified content should fail verification."""
        public_key = get_public_key_bytes(signing_key)

        tampered_vc = signed_vc.copy()
        tampered_vc["credentialSubject"]["version"] = 999

        result = verify_vc_signature(tampered_vc, public_key)

        assert result is False

    def test_verify_vc_signature_wrong_public_key_returns_false(self, signed_vc):
        """VC verified with wrong public key should return False."""
        wrong_key = create_keypair_from_hex("b" * 64)
        wrong_public = get_public_key_bytes(wrong_key)

        result = verify_vc_signature(signed_vc, wrong_public)

        assert result is False

    def test_verify_vc_signature_wrong_signature_length_returns_false(self, signed_vc, signing_key):
        """VC with wrong signature length should return False."""
        public_key = get_public_key_bytes(signing_key)

        vc_bad_sig_len = signed_vc.copy()
        # Create signature with wrong length (32 bytes instead of 64)
        vc_bad_sig_len["proof"]["proofValue"] = encode_multibase_base64url(b"x" * 32)

        result = verify_vc_signature(vc_bad_sig_len, public_key)

        assert result is False


# =============================================================================
# TestVerifyVPSignature
# =============================================================================

class TestVerifyVPSignature:
    """Tests for verify_vp_signature function."""

    def test_verify_vp_signature_valid_signature_returns_true(
        self,
        sample_vp,
        sample_secret_key_hex,
        signing_key
    ):
        """Valid VP signature should verify successfully."""
        verification_method = "did:web:did.amd.com:holder123#key-1"
        signed_vp = sign_vp(sample_vp, sample_secret_key_hex, verification_method)

        public_key = get_public_key_bytes(signing_key)
        result = verify_vp_signature(signed_vp, public_key)

        assert result is True

    def test_verify_vp_signature_missing_proof_returns_false(self, sample_vp, signing_key):
        """VP without proof should return False."""
        public_key = get_public_key_bytes(signing_key)

        result = verify_vp_signature(sample_vp, public_key)

        assert result is False

    def test_verify_vp_signature_tampered_vp_returns_false(
        self,
        sample_vp,
        sample_secret_key_hex,
        signing_key
    ):
        """VP with modified content should fail verification."""
        verification_method = "did:web:did.amd.com:holder123#key-1"
        signed_vp = sign_vp(sample_vp, sample_secret_key_hex, verification_method)

        tampered_vp = signed_vp.copy()
        tampered_vp["holder"] = "did:web:did.amd.com:different-holder"

        public_key = get_public_key_bytes(signing_key)
        result = verify_vp_signature(tampered_vp, public_key)

        assert result is False


# =============================================================================
# TestSignAndVerifyRoundTrip
# =============================================================================

class TestSignAndVerifyRoundTrip:
    """Integration tests for sign-then-verify workflows."""

    def test_vc_sign_verify_roundtrip(self, sample_vc, signing_key):
        """Signing a VC then verifying should succeed."""
        verification_method = "did:web:did.amd.com:epdw#key-1"

        # Sign
        signed = sign_vc(sample_vc, signing_key, verification_method)

        # Verify
        public_key = get_public_key_bytes(signing_key)
        result = verify_vc_signature(signed, public_key)

        assert result is True

    def test_vp_sign_verify_roundtrip(self, sample_vp, sample_secret_key_hex, signing_key):
        """Signing a VP then verifying should succeed."""
        verification_method = "did:web:did.amd.com:holder123#key-1"

        # Sign
        signed = sign_vp(sample_vp, sample_secret_key_hex, verification_method)

        # Verify
        public_key = get_public_key_bytes(signing_key)
        result = verify_vp_signature(signed, public_key)

        assert result is True

    def test_multiple_vcs_with_different_keys(self):
        """Multiple VCs with different keys should verify independently."""
        vc1 = {
            "@context": ["https://www.w3.org/2018/credentials/v1"],
            "type": ["VerifiableCredential"],
            "issuer": "did:web:did.amd.com:issuer1",
            "credentialSubject": {"id": "did:web:did.amd.com:subject1"},
        }
        vc2 = {
            "@context": ["https://www.w3.org/2018/credentials/v1"],
            "type": ["VerifiableCredential"],
            "issuer": "did:web:did.amd.com:issuer2",
            "credentialSubject": {"id": "did:web:did.amd.com:subject2"},
        }

        # Different keys
        key1 = create_keypair_from_hex("a" * 64)
        key2 = create_keypair_from_hex("b" * 64)

        # Sign with different keys
        signed1 = sign_vc(vc1, key1, "did:web:did.amd.com:issuer1#key-1")
        signed2 = sign_vc(vc2, key2, "did:web:did.amd.com:issuer2#key-1")

        # Verify with correct keys
        pub1 = get_public_key_bytes(key1)
        pub2 = get_public_key_bytes(key2)

        assert verify_vc_signature(signed1, pub1) is True
        assert verify_vc_signature(signed2, pub2) is True

        # Verify with wrong keys should fail
        assert verify_vc_signature(signed1, pub2) is False
        assert verify_vc_signature(signed2, pub1) is False

    def test_end_to_end_workflow(self):
        """Complete end-to-end workflow from key generation to verification."""
        # Generate key
        secret_hex = "c" * 64
        signing_key = create_keypair_from_hex(secret_hex)
        public_key = get_public_key_bytes(signing_key)

        # Create VC
        vc = {
            "@context": ["https://www.w3.org/2018/credentials/v1"],
            "type": ["VerifiableCredential"],
            "issuer": "did:web:did.amd.com:test",
            "credentialSubject": {"id": "did:web:did.amd.com:subject"},
        }

        # Sign VC
        verification_method = "did:web:did.amd.com:test#key-1"
        signed_vc = sign_vc(vc, signing_key, verification_method)

        # Verify signature
        assert verify_vc_signature(signed_vc, public_key) is True

        # Create VP with the signed VC
        vp = {
            "@context": ["https://www.w3.org/2018/credentials/v1"],
            "type": ["VerifiablePresentation"],
            "holder": "did:web:did.amd.com:holder",
            "verifiableCredential": [signed_vc],
        }

        # Sign VP
        vp_verification_method = "did:web:did.amd.com:holder#key-1"
        signed_vp = sign_vp(vp, secret_hex, vp_verification_method)

        # Verify VP signature
        assert verify_vp_signature(signed_vp, public_key) is True

        # Embedded VC should still have its proof
        embedded_vc = signed_vp["verifiableCredential"][0]
        assert "proof" in embedded_vc
        assert verify_vc_signature(embedded_vc, public_key) is True
