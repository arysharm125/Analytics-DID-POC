"""Unit tests for app/routers/basetypes.py validation functions."""

import pytest

from app.routers.basetypes import (
    validate_uuid,
    validate_amd_web_did,
    validate_amd_division_web_did,
    did_from_uuid,
    uuid_from_did,
    division_did_from_division,
    division_from_division_did,
    _validate_multihash,
    _validate_division,
    _validate_did_or_uuid,
    _canonicalize_did_or_uuid,
    _validate_and_canonicalize_did_or_uuid,
    _validate_did_or_uuid_list,
    _validate_did_list,
    did_list_from_uuid_list,
    multihash_from_str,
    division_from_str,
)
from app.services.exceptions import (
    InvalidIdentifierError,
    InvalidMultihashError,
    InvalidDivisionError,
    DuplicateProvenanceError,
)


class TestUUIDValidation:
    """Tests for UUID validation."""

    def test_valid_uuid(self):
        """Valid UUID should be returned unchanged."""
        valid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert validate_uuid(valid) == valid

    def test_valid_uuid_uppercase(self):
        """Valid UUID with uppercase should be returned unchanged."""
        valid = "95DA4DD5-6E48-4C5B-BB91-935983C16D9C"
        assert validate_uuid(valid) == valid

    def test_invalid_uuid_raises(self):
        """Invalid string should raise ValueError."""
        with pytest.raises(ValueError):
            validate_uuid("not-a-uuid")

    def test_uuid_wrong_format(self):
        """UUID with wrong structure should raise ValueError."""
        # Note: Python's UUID() accepts UUIDs without dashes, so we test with
        # an invalid structure instead
        with pytest.raises(ValueError):
            validate_uuid("95da4dd5-6e48-4c5b-bb91")  # Too short

    def test_empty_string_raises(self):
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError):
            validate_uuid("")

    def test_partial_uuid_raises(self):
        """Partial UUID should raise ValueError."""
        with pytest.raises(ValueError):
            validate_uuid("95da4dd5-6e48-4c5b")


class TestAMDWebDIDValidation:
    """Tests for AMD Web DID validation."""

    def test_valid_did(self):
        """Valid AMD Web DID should be returned unchanged."""
        did = "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert validate_amd_web_did(did) == did

    def test_invalid_did_wrong_prefix(self):
        """DID with wrong prefix should raise ValueError."""
        with pytest.raises(ValueError):
            validate_amd_web_did("did:key:z6Mk...")

    def test_invalid_did_missing_uuid(self):
        """DID without UUID should raise ValueError."""
        with pytest.raises(ValueError):
            validate_amd_web_did("did:web:did.amd.com:")

    def test_invalid_did_wrong_domain(self):
        """DID with wrong domain should raise ValueError."""
        with pytest.raises(ValueError):
            validate_amd_web_did("did:web:example.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c")

    def test_invalid_did_extra_path_segments(self):
        """DID with extra path segments should raise ValueError."""
        with pytest.raises(ValueError):
            validate_amd_web_did("did:web:did.amd.com:extra:95da4dd5-6e48-4c5b-bb91-935983c16d9c")


class TestDIDConversion:
    """Tests for DID <-> UUID conversion."""

    def test_did_from_uuid(self):
        """UUID should be converted to proper DID format."""
        uuid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        expected = "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert did_from_uuid(uuid) == expected

    def test_uuid_from_did(self):
        """DID should be converted back to UUID."""
        did = "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        expected = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert uuid_from_did(did) == expected

    def test_uuid_from_did_wrong_domain(self):
        """Invalid AMDWebDID (wrong domain) fails to convert."""
        with pytest.raises(ValueError):
            uuid_from_did("did:web:did.amd.net:95da4dd5-6e48-4c5b-bb91-935983c16d9c")

    def test_uuid_from_did_wrong_method(self):
        """Invalid AMDWebDID (wrong method) fails to convert."""
        with pytest.raises(ValueError):
            uuid_from_did("did:key:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c")

    def test_uuid_from_did_wrong_scheme(self):
        """Invalid AMDWebDID (wrong did scheme) fails to convert."""
        with pytest.raises(ValueError):
            uuid_from_did("dId:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c")

    def test_uuid_from_did_wrong_uid(self):
        """Invalid AMDWebDID (wrong uid) fails to convert."""
        with pytest.raises(ValueError):
            uuid_from_did("did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9X")

    def test_roundtrip(self):
        """Conversion should be reversible."""
        uuid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert uuid_from_did(did_from_uuid(uuid)) == uuid


class TestDivisionDIDConversion:
    """Tests for Division DID <-> Division conversion."""

    def test_division_did_from_division(self):
        """Division should be converted to proper Division DID format."""
        division = "advisory"
        expected = "did:web:did.amd.com:advisory"
        assert division_did_from_division(division) == expected

    def test_division_from_division_did(self):
        """Division DID should be converted back to division."""
        did = "did:web:did.amd.com:epdw"
        expected = "epdw"
        assert division_from_division_did(did) == expected

    def test_roundtrip(self):
        """Conversion should be reversible."""
        division = "my_division_123"
        assert division_from_division_did(division_did_from_division(division)) == division


class TestAMDDivisionWebDIDValidation:
    """Tests for AMD Division Web DID validation."""

    def test_valid_division_did(self):
        """Valid AMD Division Web DID should be returned unchanged."""
        did = "did:web:did.amd.com:advisory"
        assert validate_amd_division_web_did(did) == did

    def test_valid_division_did_with_underscore(self):
        """Division DID with underscore should be valid."""
        did = "did:web:did.amd.com:my_division_123"
        assert validate_amd_division_web_did(did) == did

    def test_invalid_division_did_starts_with_number(self):
        """Division DID where division starts with number should raise."""
        with pytest.raises(ValueError):
            validate_amd_division_web_did("did:web:did.amd.com:1division")

    def test_invalid_division_did_uppercase(self):
        """Division DID with uppercase should raise."""
        with pytest.raises(ValueError):
            validate_amd_division_web_did("did:web:did.amd.com:Advisory")


class TestMultihashValidation:
    """Tests for multihash validation."""

    def test_valid_sha256_multihash(self):
        """Valid base58btc SHA-256 multihash should pass."""
        # Valid base58btc SHA-256 multihash (46 chars, starts with Qm)
        valid = "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"
        assert _validate_multihash(valid) == valid

    def test_invalid_prefix(self):
        """Multihash with wrong prefix should raise InvalidMultihashError."""
        with pytest.raises(InvalidMultihashError) as exc:
            _validate_multihash("XmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk")
        assert "SHA-256" in str(exc.value)

    def test_invalid_length_too_short(self):
        """Multihash with wrong length should raise InvalidMultihashError."""
        with pytest.raises(InvalidMultihashError) as exc:
            _validate_multihash("QmTooShort")
        assert "46 characters" in str(exc.value)

    def test_invalid_length_too_long(self):
        """Multihash that's too long should raise InvalidMultihashError."""
        with pytest.raises(InvalidMultihashError) as exc:
            _validate_multihash("QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDkXXXXX")
        assert "46 characters" in str(exc.value)

    def test_empty_multihash(self):
        """Empty multihash should raise InvalidMultihashError."""
        with pytest.raises(InvalidMultihashError) as exc:
            _validate_multihash("")
        assert "empty" in str(exc.value).lower()

    def test_invalid_characters(self):
        """Multihash with invalid base58btc characters should raise."""
        with pytest.raises(InvalidMultihashError) as exc:
            # '0' is not in base58btc alphabet
            _validate_multihash("Qm0wAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk")
        assert "base58btc" in str(exc.value).lower()


class TestDivisionValidation:
    """Tests for division identifier validation."""

    def test_valid_division(self):
        """Valid divisions should pass."""
        assert _validate_division("advisory") == "advisory"
        assert _validate_division("epdw") == "epdw"
        assert _validate_division("division_1") == "division_1"

    def test_valid_division_with_numbers(self):
        """Division with numbers (not at start) should pass."""
        assert _validate_division("div123") == "div123"

    def test_invalid_starts_with_number(self):
        """Division starting with number should raise."""
        with pytest.raises(InvalidDivisionError):
            _validate_division("1division")

    def test_invalid_starts_with_underscore(self):
        """Division starting with underscore should raise."""
        with pytest.raises(InvalidDivisionError):
            _validate_division("_division")

    def test_invalid_uppercase(self):
        """Division with uppercase should raise."""
        with pytest.raises(InvalidDivisionError):
            _validate_division("Advisory")

    def test_invalid_hyphen(self):
        """Division with hyphen should raise."""
        with pytest.raises(InvalidDivisionError):
            _validate_division("my-division")

    def test_empty_division(self):
        """Empty division should raise."""
        with pytest.raises(InvalidDivisionError):
            _validate_division("")


class TestDIDOrUUIDValidation:
    """Tests for DID or UUID validation."""

    def test_valid_uuid(self):
        """Valid UUID should pass."""
        uuid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert _validate_did_or_uuid(uuid) == uuid

    def test_valid_did(self):
        """Valid AMD Web DID should pass."""
        did = "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert _validate_did_or_uuid(did) == did

    def test_invalid_identifier(self):
        """Invalid identifier should raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError):
            _validate_did_or_uuid("not-valid")


class TestCanonicalizeDidOrUUID:
    """Tests for DID/UUID canonicalization."""

    def test_uuid_unchanged(self):
        """UUID should be returned unchanged."""
        uuid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert _canonicalize_did_or_uuid(uuid) == uuid

    def test_did_canonicalized_to_uuid(self):
        """DID should be canonicalized to UUID portion."""
        did = "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        expected = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert _canonicalize_did_or_uuid(did) == expected


class TestValidateAndCanonicalizeDidOrUUID:
    """Tests for combined validation and canonicalization."""

    def test_valid_uuid(self):
        """Valid UUID should be validated and returned unchanged."""
        uuid = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert _validate_and_canonicalize_did_or_uuid(uuid) == uuid

    def test_valid_did_canonicalized(self):
        """Valid DID should be validated and canonicalized."""
        did = "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        expected = "95da4dd5-6e48-4c5b-bb91-935983c16d9c"
        assert _validate_and_canonicalize_did_or_uuid(did) == expected

    def test_invalid_raises(self):
        """Invalid identifier should raise InvalidIdentifierError."""
        with pytest.raises(InvalidIdentifierError):
            _validate_and_canonicalize_did_or_uuid("invalid")


class TestValidateDidOrUUIDList:
    """Tests for DID/UUID list validation."""

    def test_empty_list(self):
        """Empty list should be valid."""
        assert _validate_did_or_uuid_list([]) == []

    def test_list_of_uuids(self):
        """List of UUIDs should be validated."""
        uuids = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "11111111-2222-3333-4444-555555555555",
        ]
        result = _validate_did_or_uuid_list(uuids)
        assert result == uuids

    def test_list_of_dids_canonicalized(self):
        """List of DIDs should be canonicalized to UUIDs."""
        dids = [
            "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
        ]
        expected = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "11111111-2222-3333-4444-555555555555",
        ]
        result = _validate_did_or_uuid_list(dids)
        assert result == expected

    def test_mixed_list(self):
        """Mixed list of DIDs and UUIDs should work."""
        mixed = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
        ]
        expected = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "11111111-2222-3333-4444-555555555555",
        ]
        result = _validate_did_or_uuid_list(mixed)
        assert result == expected

    def test_duplicate_uuids_raises(self):
        """Duplicate UUIDs should raise DuplicateProvenanceError."""
        uuids = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
        ]
        with pytest.raises(DuplicateProvenanceError):
            _validate_did_or_uuid_list(uuids)

    def test_duplicate_after_canonicalization_raises(self):
        """Duplicates after canonicalization should raise DuplicateProvenanceError."""
        items = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
        ]
        with pytest.raises(DuplicateProvenanceError):
            _validate_did_or_uuid_list(items)

    def test_invalid_item_raises(self):
        """Invalid item in list should raise InvalidIdentifierError."""
        items = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "not-valid",
        ]
        with pytest.raises(InvalidIdentifierError):
            _validate_did_or_uuid_list(items)


class TestDIDListConversion:
    """Tests for DIDList type and did_list_from_uuid_list conversion."""

    def test_did_list_from_uuid_list_single(self):
        """Single UUID should be converted to DID."""
        uuids = ["95da4dd5-6e48-4c5b-bb91-935983c16d9c"]
        expected = ["did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"]
        assert did_list_from_uuid_list(uuids) == expected

    def test_did_list_from_uuid_list_multiple(self):
        """Multiple UUIDs should be converted to DIDs."""
        uuids = [
            "95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "11111111-2222-3333-4444-555555555555",
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ]
        expected = [
            "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
            "did:web:did.amd.com:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ]
        assert did_list_from_uuid_list(uuids) == expected

    def test_did_list_from_uuid_list_empty(self):
        """Empty list should return empty list."""
        assert did_list_from_uuid_list([]) == []

    def test_did_list_from_uuid_list_preserves_order(self):
        """Order of UUIDs should be preserved in resulting DIDs."""
        uuids = [
            "33333333-3333-3333-3333-333333333333",
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]
        result = did_list_from_uuid_list(uuids)
        # Check order is preserved by verifying UUIDs extracted from DIDs
        for i, did in enumerate(result):
            assert uuids[i] in did


class TestMultihashFromStr:
    """Tests for multihash_from_str function."""

    def test_valid_multihash(self):
        """Valid SHA-256 multihash should pass and return the value."""
        valid = "QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk"
        assert multihash_from_str(valid) == valid

    def test_valid_multihash_alternate(self):
        """Another valid SHA-256 multihash should pass."""
        # Valid 46-char base58btc SHA-256 multihash starting with Qm
        valid = "QmXnnyufdzAWL5CqZ2RnSNgPbvCc1ALT73s6epPrRnZ1Xy"
        assert multihash_from_str(valid) == valid

    def test_empty_string_raises(self):
        """Empty string should raise InvalidMultihashError."""
        with pytest.raises(InvalidMultihashError) as exc:
            multihash_from_str("")
        assert "empty" in str(exc.value).lower()

    def test_invalid_prefix_raises(self):
        """Multihash with wrong prefix should raise InvalidMultihashError."""
        with pytest.raises(InvalidMultihashError) as exc:
            multihash_from_str("XmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk")
        assert "SHA-256" in str(exc.value)

    def test_too_short_raises(self):
        """Multihash that's too short should raise InvalidMultihashError."""
        with pytest.raises(InvalidMultihashError) as exc:
            multihash_from_str("QmTooShort")
        assert "46 characters" in str(exc.value)

    def test_too_long_raises(self):
        """Multihash that's too long should raise InvalidMultihashError."""
        with pytest.raises(InvalidMultihashError) as exc:
            multihash_from_str("QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDkExtra")
        assert "46 characters" in str(exc.value)

    def test_invalid_base58btc_chars_raises(self):
        """Multihash with invalid base58btc characters should raise."""
        with pytest.raises(InvalidMultihashError) as exc:
            # '0', 'O', 'I', 'l' are not in base58btc alphabet
            multihash_from_str("Qm0wAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk")
        assert "base58btc" in str(exc.value).lower()


class TestDivisionFromStr:
    """Tests for division_from_str function."""

    def test_valid_division(self):
        """Valid division should pass and return the value."""
        assert division_from_str("advisory") == "advisory"

    def test_valid_division_with_underscore(self):
        """Division with underscore should pass."""
        assert division_from_str("my_division") == "my_division"

    def test_valid_division_with_numbers(self):
        """Division with numbers (not at start) should pass."""
        assert division_from_str("division123") == "division123"
        assert division_from_str("div_123_test") == "div_123_test"

    def test_empty_string_raises(self):
        """Empty string should raise InvalidDivisionError."""
        with pytest.raises(InvalidDivisionError):
            division_from_str("")

    def test_starts_with_number_raises(self):
        """Division starting with number should raise InvalidDivisionError."""
        with pytest.raises(InvalidDivisionError):
            division_from_str("1division")

    def test_starts_with_underscore_raises(self):
        """Division starting with underscore should raise InvalidDivisionError."""
        with pytest.raises(InvalidDivisionError):
            division_from_str("_division")

    def test_uppercase_raises(self):
        """Division with uppercase letters should raise InvalidDivisionError."""
        with pytest.raises(InvalidDivisionError):
            division_from_str("Advisory")

    def test_hyphen_raises(self):
        """Division with hyphen should raise InvalidDivisionError."""
        with pytest.raises(InvalidDivisionError):
            division_from_str("my-division")

    def test_space_raises(self):
        """Division with space should raise InvalidDivisionError."""
        with pytest.raises(InvalidDivisionError):
            division_from_str("my division")


class TestDivisionFromDivisionDIDNegative:
    """Negative tests for division_from_division_did function."""

    def test_invalid_prefix_raises(self):
        """DID with wrong prefix should raise ValueError."""
        with pytest.raises(ValueError) as exc:
            division_from_division_did("did:key:advisory")
        assert "Invalid AMD Division DID format" in str(exc.value)

    def test_wrong_domain_raises(self):
        """DID with wrong domain should raise ValueError."""
        with pytest.raises(ValueError) as exc:
            division_from_division_did("did:web:example.com:advisory")
        assert "Invalid AMD Division DID format" in str(exc.value)

    def test_empty_division_raises(self):
        """DID with empty division should raise ValueError."""
        with pytest.raises(ValueError) as exc:
            division_from_division_did("did:web:did.amd.com:")
        assert "Invalid AMD Division DID format" in str(exc.value)

    def test_division_starts_with_number_raises(self):
        """DID where division starts with number should raise ValueError."""
        with pytest.raises(ValueError) as exc:
            division_from_division_did("did:web:did.amd.com:1division")
        assert "Invalid AMD Division DID format" in str(exc.value)

    def test_division_uppercase_raises(self):
        """DID where division has uppercase should raise ValueError."""
        with pytest.raises(ValueError) as exc:
            division_from_division_did("did:web:did.amd.com:Advisory")
        assert "Invalid AMD Division DID format" in str(exc.value)

    def test_completely_invalid_string_raises(self):
        """Completely invalid string should raise ValueError."""
        with pytest.raises(ValueError) as exc:
            division_from_division_did("not-a-did-at-all")
        assert "Invalid AMD Division DID format" in str(exc.value)

    def test_uuid_did_instead_of_division_did_raises(self):
        """UUID-based DID should raise ValueError (wrong format for division)."""
        # This is a valid AMD Web DID but not a valid Division DID
        with pytest.raises(ValueError) as exc:
            division_from_division_did("did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c")
        assert "Invalid AMD Division DID format" in str(exc.value)


class TestValidateDIDList:
    """Tests for _validate_did_list function."""

    def test_empty_list(self):
        """Empty list should be valid."""
        assert _validate_did_list([]) == []

    def test_single_valid_did(self):
        """Single valid DID should be validated and returned."""
        dids = ["did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"]
        assert _validate_did_list(dids) == dids

    def test_multiple_valid_dids(self):
        """Multiple valid DIDs should be validated and returned."""
        dids = [
            "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "did:web:did.amd.com:11111111-2222-3333-4444-555555555555",
            "did:web:did.amd.com:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        ]
        assert _validate_did_list(dids) == dids

    def test_preserves_order(self):
        """Order of DIDs should be preserved."""
        dids = [
            "did:web:did.amd.com:33333333-3333-3333-3333-333333333333",
            "did:web:did.amd.com:11111111-1111-1111-1111-111111111111",
            "did:web:did.amd.com:22222222-2222-2222-2222-222222222222",
        ]
        result = _validate_did_list(dids)
        assert result == dids

    def test_invalid_did_raises(self):
        """Invalid DID should raise ValueError."""
        dids = [
            "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "not-a-valid-did",
        ]
        with pytest.raises(ValueError):
            _validate_did_list(dids)

    def test_uuid_instead_of_did_raises(self):
        """UUID (not a DID) should raise ValueError."""
        items = [
            "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "11111111-2222-3333-4444-555555555555",  # UUID, not DID
        ]
        with pytest.raises(ValueError):
            _validate_did_list(items)

    def test_wrong_domain_raises(self):
        """DID with wrong domain should raise ValueError."""
        dids = ["did:web:example.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c"]
        with pytest.raises(ValueError):
            _validate_did_list(dids)

    def test_duplicate_dids_raises(self):
        """Duplicate DIDs should raise DuplicateProvenanceError."""
        dids = [
            "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
            "did:web:did.amd.com:95da4dd5-6e48-4c5b-bb91-935983c16d9c",
        ]
        with pytest.raises(DuplicateProvenanceError):
            _validate_did_list(dids)

    def test_division_did_instead_of_uuid_did_raises(self):
        """Division DID should raise ValueError (expected UUID-based DID)."""
        # Division DIDs don't match the AMD Web DID pattern which requires UUID
        dids = ["did:web:did.amd.com:advisory"]
        with pytest.raises(ValueError):
            _validate_did_list(dids)


class TestArtefactTypeValidation:
    """Tests for artefact type identifier validation."""

    def test_valid_simple_type(self):
        """Simple artefact type should pass."""
        from app.routers.basetypes import _validate_artefact_type
        assert _validate_artefact_type("report") == "report"
        assert _validate_artefact_type("benchmark") == "benchmark"

    def test_valid_with_underscore(self):
        """Artefact type with underscore should pass."""
        from app.routers.basetypes import _validate_artefact_type
        assert _validate_artefact_type("benchmark_iteration") == "benchmark_iteration"
        assert _validate_artefact_type("my_type_v2") == "my_type_v2"

    def test_valid_with_hyphen(self):
        """Artefact type with hyphen should pass."""
        from app.routers.basetypes import _validate_artefact_type
        assert _validate_artefact_type("my-type") == "my-type"
        assert _validate_artefact_type("report-v2") == "report-v2"

    def test_valid_with_colon(self):
        """Artefact type with colon should pass."""
        from app.routers.basetypes import _validate_artefact_type
        assert _validate_artefact_type("type:subtype") == "type:subtype"
        assert _validate_artefact_type("namespace:type:version") == "namespace:type:version"

    def test_valid_with_slash(self):
        """Artefact type with slash should pass."""
        from app.routers.basetypes import _validate_artefact_type
        assert _validate_artefact_type("type/subtype") == "type/subtype"
        assert _validate_artefact_type("path/to/type") == "path/to/type"

    def test_valid_complex_combination(self):
        """Complex artefact type with all allowed chars should pass."""
        from app.routers.basetypes import _validate_artefact_type
        assert _validate_artefact_type("my-type_v2:sub/path") == "my-type_v2:sub/path"

    def test_invalid_starts_with_number(self):
        """Artefact type starting with number should raise."""
        from app.routers.basetypes import _validate_artefact_type
        from app.services.exceptions import InvalidArtefactTypeError
        with pytest.raises(InvalidArtefactTypeError):
            _validate_artefact_type("123type")

    def test_invalid_uppercase(self):
        """Artefact type with uppercase should raise."""
        from app.routers.basetypes import _validate_artefact_type
        from app.services.exceptions import InvalidArtefactTypeError
        with pytest.raises(InvalidArtefactTypeError):
            _validate_artefact_type("Report")
        with pytest.raises(InvalidArtefactTypeError):
            _validate_artefact_type("BENCHMARK")

    def test_invalid_space(self):
        """Artefact type with space should raise."""
        from app.routers.basetypes import _validate_artefact_type
        from app.services.exceptions import InvalidArtefactTypeError
        with pytest.raises(InvalidArtefactTypeError):
            _validate_artefact_type("my type")

    def test_invalid_special_chars(self):
        """Artefact type with invalid special chars should raise."""
        from app.routers.basetypes import _validate_artefact_type
        from app.services.exceptions import InvalidArtefactTypeError
        with pytest.raises(InvalidArtefactTypeError):
            _validate_artefact_type("type@version")
        with pytest.raises(InvalidArtefactTypeError):
            _validate_artefact_type("type.subtype")

    def test_empty_string_raises(self):
        """Empty artefact type should raise."""
        from app.routers.basetypes import _validate_artefact_type
        from app.services.exceptions import InvalidArtefactTypeError
        with pytest.raises(InvalidArtefactTypeError):
            _validate_artefact_type("")
