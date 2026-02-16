"""EdDSA (Ed25519) signature utilities for Verifiable Credentials.

This module provides functions for signing and verifying Verifiable Credentials
and Verifiable Presentations using EdDSA signatures with Ed25519 keys,
following the W3C VC Data Integrity eddsa-rdfc-2022 cryptosuite specification.
"""

import base64
import gc
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

import base58
from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError
from nacl._sodium import ffi as nacl_ffi, lib as nacl_lib

from app.did_utils.jsonld import (
    prepare_vc_for_signing,
    prepare_vp_for_signing,
    create_proof_options,
    canonicalize_document,
)

# EdDSA cryptosuite identifier (W3C VC Data Integrity)
EDDSA_RDFC_2022_CRYPTOSUITE = "eddsa-rdfc-2022"

# Multicodec prefix for Ed25519 public keys
MULTICODEC_ED25519_PUB = bytes([0xed, 0x01])

# Multibase prefix for base58btc encoding
MULTIBASE_BASE58BTC_PREFIX = "z"

# Multibase prefix for base64url encoding (used in proof values)
MULTIBASE_BASE64URL_PREFIX = "u"


class EdDSASigningError(Exception):
    """Raised when EdDSA signing operations fail."""
    pass


def encode_multibase_base64url(data: bytes) -> str:
    """Encode bytes as multibase base64url string.

    Args:
        data: The bytes to encode

    Returns:
        Multibase-encoded string with 'u' prefix (base64url, no padding)
    """
    encoded = base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')
    return f"{MULTIBASE_BASE64URL_PREFIX}{encoded}"


def decode_multibase_base64url(multibase_str: str) -> bytes:
    """Decode a multibase base64url string to bytes.

    Args:
        multibase_str: Multibase-encoded string (must start with 'u')

    Returns:
        Decoded bytes

    Raises:
        ValueError: If the string is not valid multibase base64url
    """
    if not multibase_str.startswith(MULTIBASE_BASE64URL_PREFIX):
        raise ValueError(
            f"Expected multibase prefix '{MULTIBASE_BASE64URL_PREFIX}', "
            f"got '{multibase_str[0] if multibase_str else ''}'"
        )

    encoded = multibase_str[1:]

    # Add padding if needed for base64url decoding
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += '=' * padding

    return base64.urlsafe_b64decode(encoded)


def create_keypair_from_hex(secret_key_hex: str) -> SigningKey:
    """Create an Ed25519 signing key from a hex-encoded seed.

    Args:
        secret_key_hex: 32-byte seed encoded as hex string

    Returns:
        nacl.signing.SigningKey instance

    Raises:
        ValueError: If the hex string is invalid or wrong length
    """
    try:
        seed = bytes.fromhex(secret_key_hex)
    except ValueError as e:
        raise ValueError(f"Invalid hex string for secret key: {e}") from e

    if len(seed) != 32:
        raise ValueError(
            f"Secret key seed must be 32 bytes, got {len(seed)} bytes"
        )

    return SigningKey(seed)


def get_public_key_multibase(signing_key: SigningKey) -> str:
    """Get the public key in multibase (base58btc) format.

    This format is used in did:key identifiers and Multikey verification
    methods for Ed25519 keys. The multicodec prefix for Ed25519 public
    keys is 0xed01.

    Args:
        signing_key: The Ed25519 signing key

    Returns:
        Multibase-encoded public key string (z-prefixed base58btc)
    """
    verify_key = signing_key.verify_key
    prefixed_key = MULTICODEC_ED25519_PUB + bytes(verify_key)
    encoded = base58.b58encode(prefixed_key).decode('utf-8')
    return f"{MULTIBASE_BASE58BTC_PREFIX}{encoded}"


def get_public_key_bytes(signing_key: SigningKey) -> bytes:
    """Get the raw public key bytes.

    Args:
        signing_key: The Ed25519 signing key

    Returns:
        32-byte Ed25519 public key
    """
    return bytes(signing_key.verify_key)


def sign_data(signing_key: SigningKey, data: bytes) -> bytes:
    """Sign data using Ed25519.

    Args:
        signing_key: The Ed25519 signing key
        data: The data to sign

    Returns:
        64-byte Ed25519 signature

    Raises:
        EdDSASigningError: If signing fails
    """
    try:
        print(f"Data to sign (hex): {data.hex()}")
        signed = signing_key.sign(data)
        return signed.signature
    except Exception as e:
        raise EdDSASigningError(f"EdDSA signing failed: {e}") from e


def verify_signature(
    public_key_bytes: bytes,
    data: bytes,
    signature: bytes
) -> bool:
    """Verify an Ed25519 signature.

    Args:
        public_key_bytes: 32-byte Ed25519 public key
        data: The data that was signed
        signature: 64-byte Ed25519 signature

    Returns:
        True if signature is valid, False otherwise
    """
    try:
        verify_key = VerifyKey(public_key_bytes)
        verify_key.verify(data, signature)
        return True
    except BadSignatureError:
        return False
    except Exception:
        return False


def sodium_memzero(buffer: bytes | bytearray) -> None:
    """Securely zero memory using libsodium's sodium_memzero.

    This function uses libsodium's secure memory zeroing, which is designed
    to prevent compiler optimization from skipping the memory clearing.

    Args:
        buffer: The bytes or bytearray object whose underlying memory should
                be zeroed. WARNING: The buffer should not be used after this call.

    Note:
        This operates on the buffer's internal memory via cffi.
        Due to Python's memory model, the bytes object may have been
        copied elsewhere, but this ensures the primary buffer is cleared.
        For bytearray, this is more effective since bytearray is mutable.
    """
    if len(buffer) == 0:
        return
    try:
        buf_ptr = nacl_ffi.from_buffer(buffer)
        nacl_lib.sodium_memzero(buf_ptr, len(buffer))
    except Exception:
        # Silently ignore errors - this is a best-effort security measure
        pass


# Alias for backward compatibility
_sodium_memzero = sodium_memzero


def secure_clear_signing_key(signing_key: SigningKey, trigger_gc: bool = True) -> None:
    """Attempt to securely clear a SigningKey's secret material from memory.

    This function uses libsodium's sodium_memzero to zero out the key material
    in memory. sodium_memzero is specifically designed to resist compiler
    optimizations that might skip memory clearing.

    Due to Python's memory model (immutable bytes, object copying,
    garbage collection), complete erasure cannot be guaranteed, but
    sodium_memzero provides stronger guarantees than standard memset.

    For production systems requiring absolute guarantees, consider using:
    - Hardware Security Modules (HSM)
    - Separate key-handling processes with controlled memory

    Args:
        signing_key: The Ed25519 SigningKey to clear

    Note:
        This function silently ignores errors to ensure it doesn't
        disrupt the calling code's exception handling.
    """
    try:
        # Get the internal seed bytes (32 bytes for Ed25519)
        # PyNaCl stores the seed in the SigningKey object
        seed = signing_key.encode()

        # Use libsodium's sodium_memzero for secure memory clearing
        # This is resistant to compiler optimization unlike memset
        _sodium_memzero(seed)

        # Also try to clear any cached verify_key (public key)
        # While not as sensitive as the private key, clearing it
        # reduces the information available to an attacker
        try:
            vk = signing_key.verify_key
            vk_bytes = bytes(vk)
            _sodium_memzero(vk_bytes)
        except Exception:
            pass

        # Delete local references
        del seed

    except Exception:
        # Silently ignore errors - this is a best-effort security measure
        pass
    finally:
        # Force garbage collection to clean up any remaining references
        if trigger_gc:
            gc.collect()


@contextmanager
def secure_signing_context(signing_key: SigningKey) -> Generator[SigningKey, None, None]:
    """Context manager that ensures signing key is cleared after use.

    This provides a guaranteed cleanup mechanism that runs regardless of
    whether the signing operation succeeds or raises an exception.

    Usage:
        with secure_signing_context(signing_key) as key:
            signature = sign_data(key, data)
        # Key material is cleared here, even if an exception occurred

    Args:
        signing_key: The Ed25519 SigningKey to use and then clear

    Yields:
        The same SigningKey, for use within the context block

    Note:
        The key clearing is best-effort. See secure_clear_signing_key
        for details on the limitations.
    """
    try:
        yield signing_key
    finally:
        secure_clear_signing_key(signing_key)


def _create_verify_data(document: dict, proof_options: dict) -> bytes:
    """Create the data to be signed/verified.

    According to the eddsa-rdfc-2022 spec, the verify data is the
    concatenation of the proof options hash and the document hash.

    Args:
        document: The document (without proof)
        proof_options: The proof options

    Returns:
        Bytes to be signed
    """
    import hashlib

    # Canonicalize and hash the proof options
    proof_options_canonical = canonicalize_document(proof_options)
    proof_options_hash = hashlib.sha256(proof_options_canonical.encode('utf-8')).digest()

    # Canonicalize and hash the document
    document_canonical = canonicalize_document(document)
    fname = f"/tmp/canonical_document_{uuid.uuid4().hex}.txt"
    with open(fname, "w") as f:
        f.write(document_canonical)
    print(f"XXXXXXXX saved to {fname}")
    document_hash = hashlib.sha256(document_canonical.encode('utf-8')).digest()

    # Concatenate hashes
    return proof_options_hash + document_hash


def sign_vc(
    vc: dict,
    secret_key: SigningKey,
    verification_method: str,
    created: datetime | None = None,
) -> dict:
    """Sign a Verifiable Credential with EdDSA Data Integrity proof.

    This function:
    1. Prepares the VC by removing any existing proof
    2. Creates proof options and canonicalizes them
    3. Canonicalizes the VC
    4. Signs the concatenated hashes
    5. Returns the VC with DataIntegrityProof attached

    Args:
        vc: The unsigned Verifiable Credential
        secret_key: The key to use for signing
        verification_method: DID URL of the verification method
        created: ISO 8601 timestamp (generated if not provided)

    Returns:
        The signed Verifiable Credential with eddsa-rdfc-2022 proof

    Raises:
        EdDSASigningError: If signing fails
    """
    # Prepare VC (remove any existing proof, ensure contexts)
    vc_without_proof, _ = prepare_vc_for_signing(vc)

    # Create proof options
    if created is None:
        created = datetime.now(timezone.utc)

    proof_options = create_proof_options(
        verification_method=verification_method,
        proof_purpose="assertionMethod",
        created=created.isoformat(),
        cryptosuite=EDDSA_RDFC_2022_CRYPTOSUITE
    )

    # Create verify data and sign
    verify_data = _create_verify_data(vc_without_proof, proof_options)
    signature = sign_data(secret_key, verify_data)

    # Encode signature as multibase
    proof_value = encode_multibase_base64url(signature)

    # Build the Data Integrity proof
    proof = {
        "type": "DataIntegrityProof",
        "cryptosuite": EDDSA_RDFC_2022_CRYPTOSUITE,
        "created": created,
        "verificationMethod": verification_method,
        "proofPurpose": "assertionMethod",
        "proofValue": proof_value
    }

    # Return VC with proof
    signed_vc = dict(vc_without_proof)
    signed_vc["proof"] = proof

    return signed_vc


def sign_vp(
    vp: dict,
    secret_key_hex: str,
    verification_method: str,
    created: str | None = None,
    proof_purpose: str = "assertionMethod",
) -> dict:
    """Sign a Verifiable Presentation with EdDSA Data Integrity proof.

    This function signs the VP itself. The VCs inside should already
    be signed with their own proofs.

    Args:
        vp: The unsigned Verifiable Presentation
        secret_key_hex: Hex-encoded Ed25519 seed (32 bytes)
        verification_method: DID URL of the verification method
        created: ISO 8601 timestamp (generated if not provided)
        proof_purpose: The purpose of the proof (default: "authentication")

    Returns:
        The signed Verifiable Presentation with eddsa-rdfc-2022 proof

    Raises:
        EdDSASigningError: If signing fails
    """
    signing_key = create_keypair_from_hex(secret_key_hex)

    # Prepare VP (remove any existing proof, ensure contexts)
    vp_without_proof, _ = prepare_vp_for_signing(vp)

    # Create proof options
    if created is None:
        created = datetime.now(timezone.utc).isoformat()

    proof_options = create_proof_options(
        verification_method=verification_method,
        proof_purpose=proof_purpose,
        created=created,
        cryptosuite=EDDSA_RDFC_2022_CRYPTOSUITE
    )

    # Create verify data and sign
    verify_data = _create_verify_data(vp_without_proof, proof_options)
    signature = sign_data(signing_key, verify_data)

    # Encode signature as multibase
    proof_value = encode_multibase_base64url(signature)

    # Build the Data Integrity proof
    proof = {
        "type": "DataIntegrityProof",
        "cryptosuite": EDDSA_RDFC_2022_CRYPTOSUITE,
        "created": created,
        "verificationMethod": verification_method,
        "proofPurpose": proof_purpose,
        "proofValue": proof_value
    }

    # Return VP with proof
    signed_vp = dict(vp_without_proof)
    signed_vp["proof"] = proof

    return signed_vp


def verify_vc_signature(vc: dict, public_key_bytes: bytes) -> bool:
    """Verify an EdDSA signed Verifiable Credential.

    Args:
        vc: The signed Verifiable Credential with eddsa-rdfc-2022 proof
        public_key_bytes: The 32-byte Ed25519 public key

    Returns:
        True if signature is valid, False otherwise
    """
    proof = vc.get("proof", {})
    proof_value = proof.get("proofValue")
    if not proof_value:
        return False

    # Decode signature
    try:
        signature = decode_multibase_base64url(proof_value)
    except ValueError:
        return False

    if len(signature) != 64:
        return False

    # Prepare VC and proof options
    vc_without_proof, _ = prepare_vc_for_signing(vc)

    cryptosuite = proof.get("cryptosuite", EDDSA_RDFC_2022_CRYPTOSUITE)
    proof_options = create_proof_options(
        verification_method=proof.get("verificationMethod", ""),
        proof_purpose=proof.get("proofPurpose", "assertionMethod"),
        created=proof.get("created"),
        cryptosuite=cryptosuite
    )

    # Create verify data
    verify_data = _create_verify_data(vc_without_proof, proof_options)

    return verify_signature(public_key_bytes, verify_data, signature)


def verify_vp_signature(vp: dict, public_key_bytes: bytes) -> bool:
    """Verify an EdDSA signed Verifiable Presentation.

    Args:
        vp: The signed Verifiable Presentation with eddsa-rdfc-2022 proof
        public_key_bytes: The 32-byte Ed25519 public key

    Returns:
        True if signature is valid, False otherwise
    """
    proof = vp.get("proof", {})
    proof_value = proof.get("proofValue")
    if not proof_value:
        return False

    # Decode signature
    try:
        signature = decode_multibase_base64url(proof_value)
    except ValueError:
        return False

    if len(signature) != 64:
        return False

    # Prepare VP and proof options
    vp_without_proof, _ = prepare_vp_for_signing(vp)

    cryptosuite = proof.get("cryptosuite", EDDSA_RDFC_2022_CRYPTOSUITE)
    proof_options = create_proof_options(
        verification_method=proof.get("verificationMethod", ""),
        proof_purpose=proof.get("proofPurpose", "authentication"),
        created=proof.get("created"),
        cryptosuite=cryptosuite
    )

    # Create verify data
    verify_data = _create_verify_data(vp_without_proof, proof_options)

    return verify_signature(public_key_bytes, verify_data, signature)
