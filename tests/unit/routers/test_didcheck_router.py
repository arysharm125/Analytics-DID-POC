"""Unit tests for app/routers/generic_did_router.py.

Tests the generic DID router endpoints including the debug VC N-Quads endpoint.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import AppConfig, FeatureFlags, override_config
from app.main import app
from app.routers.dependencies import set_did_service_dependency

# =============================================================================
# Test Utilities
# =============================================================================


class AuthenticatedTestClient:
    """Test client wrapper that automatically includes authentication headers.

    This wrapper simplifies testing by automatically including default headers
    with every request, while still allowing explicit header overrides when needed.
    """

    def __init__(self, client: TestClient, default_headers: dict):
        """Initialize with a TestClient and default headers to include.

        Args:
            client: The FastAPI TestClient instance to wrap
            default_headers: Headers to automatically include with every request
        """
        self._client = client
        self._default_headers = default_headers

    @property
    def raw(self) -> TestClient:
        """Access the underlying TestClient without default headers.

        Useful for testing scenarios where headers should not be included,
        such as testing 401 responses when auth is missing.
        """
        return self._client

    def get(self, url, **kwargs):
        """Make a GET request with default headers automatically included.

        Explicit headers in kwargs will override default headers.
        """
        headers = {**self._default_headers, **kwargs.pop('headers', {})}
        return self._client.get(url, headers=headers, **kwargs)


# =============================================================================
# Test VC N-Quads Debug Endpoint
# =============================================================================


class TestArtefactVCNquads:
    """Tests for the /{uid}/vc.nq debug endpoint."""

    @pytest.fixture
    def test_artefact_uid(self, did_service_no_migrations, sample_uuid, sample_multihash):
        """Create a test artefact and return its version UID."""
        from app.services.did_service import ArtefactInput

        result = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid,
                division="epdw",
                artefact_hash=sample_multihash,
                artefact_metadata={"test": "data"},
                artefact_type="report",
            )
        )
        return result.version_uid

    @pytest.fixture
    def client_with_service(self, did_service_no_migrations, vault_service, override_test_config):
        """Create a test client with DIDService dependency override and auth headers."""
        set_did_service_dependency(did_service_no_migrations)
        vault_service.ensure_division_signing_key("epdw")
        client = TestClient(app)
        return AuthenticatedTestClient(client, {"X-API-Token": "test-didcheck-token"})

    def test_returns_text_plain_content_type(
        self, client_with_service, test_artefact_uid
    ):
        """Endpoint should return text/plain content type."""
        response = client_with_service.get(f"/didcheck/{test_artefact_uid}/vc.nq")

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"

    def test_returns_nquads_format(self, client_with_service, test_artefact_uid):
        """Endpoint should return N-Quads formatted text."""
        response = client_with_service.get(f"/didcheck/{test_artefact_uid}/vc.nq")

        assert response.status_code == 200
        nquads = response.text

        # N-Quads should be non-empty string
        assert isinstance(nquads, str)
        assert len(nquads) > 0

        # N-Quads should contain RDF triples (ending with .)
        assert "." in nquads

        # Should contain VC-related terms
        assert "VerifiableCredential" in nquads or "verifiableCredential" in nquads

    def test_excludes_proof_from_canonicalization(
        self, client_with_service, test_artefact_uid
    ):
        """The canonicalized output should not contain proof information."""
        response = client_with_service.get(f"/didcheck/{test_artefact_uid}/vc.nq")

        assert response.status_code == 200
        nquads = response.text

        # Proof-related terms should not appear in canonicalized output
        assert "proofValue" not in nquads
        assert "proofPurpose" not in nquads

    def test_output_is_deterministic(self, client_with_service, test_artefact_uid):
        """Same VC should produce identical N-Quads output."""
        response1 = client_with_service.get(f"/didcheck/{test_artefact_uid}/vc.nq")
        response2 = client_with_service.get(f"/didcheck/{test_artefact_uid}/vc.nq")

        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.text == response2.text

    def test_returns_404_when_artefact_not_found(
        self, client_with_service, sample_uuid_2
    ):
        """Endpoint should return 404 for non-existent artefact."""
        # Use a UUID that doesn't exist
        response = client_with_service.get(f"/didcheck/{sample_uuid_2}/vc.nq")

        assert response.status_code == 404

    def test_returns_404_when_feature_flag_disabled(
        self, did_service_no_migrations, test_artefact_uid, test_config
    ):
        """Endpoint should return 404 when FEATURE_DEBUG_VC_NQUADS is disabled."""
        # Create config with debug flag disabled
        config_disabled = AppConfig(
            vault=test_config.vault,
            tokens=test_config.tokens,
            collections=test_config.collections,
            features=FeatureFlags(
                didcheck_router=True,
                debug_vc_nquads=False,  # Disabled
            ),
            expose_error_details=True,
        )

        override_config(config_disabled)
        set_did_service_dependency(did_service_no_migrations)
        client = TestClient(app)

        response = client.get(
            f"/didcheck/{test_artefact_uid}/vc.nq",
            headers={"X-API-Token": "test-didcheck-token"}
        )

        assert response.status_code == 404
        assert "not enabled" in response.json()["detail"]

    def test_contains_credentialsubject_data(
        self, client_with_service, test_artefact_uid
    ):
        """N-Quads should contain credential subject information."""
        response = client_with_service.get(f"/didcheck/{test_artefact_uid}/vc.nq")

        assert response.status_code == 200
        nquads = response.text

        # Should contain credential subject related data
        # The exact format depends on canonicalization, but UID should appear
        assert test_artefact_uid in nquads

    def test_multiple_artefacts_produce_different_output(
        self, client_with_service, did_service_no_migrations, sample_uuid, sample_uuid_2
    ):
        """Different artefacts should produce different N-Quads."""
        from app.services.did_service import ArtefactInput

        # Create two different artefacts
        result1 = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid,
                division="epdw",
                artefact_metadata={"test": "data1"},
                artefact_type="report",
            )
        )

        result2 = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid_2,
                division="epdw",
                artefact_metadata={"test": "data2"},
                artefact_type="benchmark",
            )
        )

        response1 = client_with_service.get(f"/didcheck/{result1.version_uid}/vc.nq")
        response2 = client_with_service.get(f"/didcheck/{result2.version_uid}/vc.nq")

        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.text != response2.text

    def test_returns_401_with_wrong_token(
        self, client_with_service, test_artefact_uid
    ):
        """Endpoint should return 401 when provided with an invalid token."""
        response = client_with_service.get(
            f"/didcheck/{test_artefact_uid}/vc.nq",
            headers={"X-API-Token": "wrong-token"}
        )

        assert response.status_code == 401

    def test_returns_422_with_missing_token(
        self, client_with_service, test_artefact_uid
    ):
        """Endpoint should return 422 when authentication token is missing.

        FastAPI returns 422 (Unprocessable Entity) when a required parameter
        is missing, which occurs before the authentication dependency runs.
        """
        response = client_with_service.raw.get(f"/didcheck/{test_artefact_uid}/vc.nq")

        assert response.status_code == 422


# =============================================================================
# Test Artefact Versions Endpoint
# =============================================================================


class TestArtefactVersions:
    """Tests for the /{uid}/versions endpoint."""

    @pytest.fixture
    def multiple_versions(self, did_service_no_migrations, sample_uuid, sample_multihash):
        """Create multiple versions of an artefact and return version UIDs."""
        from app.services.did_service import ArtefactInput

        version_uids = []

        # Create version 1
        result1 = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid,
                division="epdw",
                artefact_hash=sample_multihash,
                artefact_metadata={"version": 1},
                artefact_type="report",
            )
        )
        version_uids.append(result1.version_uid)

        # Create version 2
        result2 = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid,
                division="epdw",
                artefact_hash=sample_multihash,
                artefact_metadata={"version": 2},
                artefact_type="report",
            )
        )
        version_uids.append(result2.version_uid)

        # Create version 3
        result3 = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid,
                division="epdw",
                artefact_hash=sample_multihash,
                artefact_metadata={"version": 3},
                artefact_type="report",
            )
        )
        version_uids.append(result3.version_uid)

        return {
            "external_uid": sample_uuid,
            "version_uids": version_uids,
        }

    @pytest.fixture
    def client_with_service(self, did_service_no_migrations, vault_service, override_test_config):
        """Create a test client with DIDService dependency override and auth headers."""
        set_did_service_dependency(did_service_no_migrations)
        vault_service.ensure_division_signing_key("epdw")
        client = TestClient(app)
        return AuthenticatedTestClient(client, {"X-API-Token": "test-didcheck-token"})

    def test_returns_all_versions_for_external_uid(
        self, client_with_service, multiple_versions
    ):
        """Endpoint should return all versions when queried with external_uid."""
        response = client_with_service.get(
            f"/didcheck/{multiple_versions['external_uid']}/versions"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["external_uid"] == multiple_versions["external_uid"]
        assert len(data["versions"]) == 3

    def test_returns_all_versions_for_version_uid(
        self, client_with_service, multiple_versions
    ):
        """Endpoint should return all versions when queried with version_uid."""
        # Query with version_uid of version 2
        response = client_with_service.get(
            f"/didcheck/{multiple_versions['version_uids'][1]}/versions"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["external_uid"] == multiple_versions["external_uid"]
        assert len(data["versions"]) == 3

    def test_versions_sorted_by_version_number(
        self, client_with_service, multiple_versions
    ):
        """Endpoint should return versions sorted by version number (ascending)."""
        response = client_with_service.get(
            f"/didcheck/{multiple_versions['external_uid']}/versions"
        )

        assert response.status_code == 200
        data = response.json()

        versions = data["versions"]
        assert len(versions) == 3
        assert versions[0]["version"] == 1
        assert versions[1]["version"] == 2
        assert versions[2]["version"] == 3

    def test_version_info_contains_required_fields(
        self, client_with_service, multiple_versions
    ):
        """Each version should contain version, version_uid, creation_date, and revoked fields."""
        response = client_with_service.get(
            f"/didcheck/{multiple_versions['external_uid']}/versions"
        )

        assert response.status_code == 200
        data = response.json()

        for version in data["versions"]:
            assert "version" in version
            assert "version_uid" in version
            assert "creation_date" in version
            assert "revoked" in version
            assert isinstance(version["version"], int)
            assert isinstance(version["revoked"], bool)

    def test_returns_404_when_artefact_not_found(
        self, client_with_service, sample_uuid_2
    ):
        """Endpoint should return 404 for non-existent artefact."""
        response = client_with_service.get(f"/didcheck/{sample_uuid_2}/versions")

        assert response.status_code == 404

    def test_returns_401_with_wrong_token(
        self, client_with_service, multiple_versions
    ):
        """Endpoint should return 401 when provided with an invalid token."""
        response = client_with_service.get(
            f"/didcheck/{multiple_versions['external_uid']}/versions",
            headers={"X-API-Token": "wrong-token"}
        )

        assert response.status_code == 401

    def test_returns_422_with_missing_token(
        self, client_with_service, multiple_versions
    ):
        """Endpoint should return 422 when authentication token is missing."""
        response = client_with_service.raw.get(
            f"/didcheck/{multiple_versions['external_uid']}/versions"
        )

        assert response.status_code == 422


# =============================================================================
# Test Artefact Descendants Endpoint
# =============================================================================


class TestArtefactDescendants:
    """Tests for the /{uid}/descendants endpoint."""

    @pytest.fixture
    def parent_with_descendants(self, did_service_no_migrations, sample_uuid, sample_multihash):
        """Create a parent artefact with multiple descendants."""
        from app.services.did_service import ArtefactInput

        # Create parent
        parent = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid,
                division="epdw",
                artefact_hash=sample_multihash,
                artefact_type="report",
            )
        )

        # Create multiple descendants (omit artefact_hash to avoid invalid multihash)
        descendants = []
        for i in range(5):
            desc = did_service_no_migrations.upsert_artefact(
                ArtefactInput(
                    external_uid=f"95da4dd5-6e48-{i:04d}-bb91-000000000100",
                    division="epdw",
                    artefact_metadata={"index": i},
                    artefact_type="benchmark",
                    provenance=[parent.version_uid],
                    created_at=datetime(2026, 2, i+1, 12, 0, 0, tzinfo=timezone.utc),
                )
            )
            descendants.append(desc)

        return {
            "parent_uid": parent.version_uid,
            "parent_external_uid": parent.external_uid,
            "descendants": descendants,
        }

    @pytest.fixture
    def client_with_service(self, did_service_no_migrations, vault_service, override_test_config):
        """Create a test client with DIDService dependency override and auth headers."""
        set_did_service_dependency(did_service_no_migrations)
        vault_service.ensure_division_signing_key("epdw")
        client = TestClient(app)
        return AuthenticatedTestClient(client, {"X-API-Token": "test-didcheck-token"})

    def test_returns_descendants_for_existing_artefact(
        self, client_with_service, parent_with_descendants
    ):
        """Endpoint should return descendants when they exist."""
        response = client_with_service.get(
            f"/didcheck/{parent_with_descendants['parent_uid']}/descendants"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["root_uid"] == parent_with_descendants["parent_uid"]
        assert len(data["descendants"]) == 5
        assert data["total_count"] == 5

    def test_pagination_parameters_work(
        self, client_with_service, parent_with_descendants
    ):
        """Endpoint should respect page and page_size parameters."""
        response = client_with_service.get(
            f"/didcheck/{parent_with_descendants['parent_uid']}/descendants?page=1&page_size=2"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 2
        assert len(data["descendants"]) == 2
        assert data["total_count"] == 5
        assert data["has_more"] is True

    def test_default_pagination_values(
        self, client_with_service, parent_with_descendants
    ):
        """Endpoint should use default pagination values when not specified."""
        response = client_with_service.get(
            f"/didcheck/{parent_with_descendants['parent_uid']}/descendants"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 20

    def test_descendant_info_contains_required_fields(
        self, client_with_service, parent_with_descendants
    ):
        """Each descendant should contain all required fields."""
        response = client_with_service.get(
            f"/didcheck/{parent_with_descendants['parent_uid']}/descendants"
        )

        assert response.status_code == 200
        data = response.json()

        for descendant in data["descendants"]:
            assert "uid" in descendant
            assert "external_uid" in descendant
            assert "division" in descendant
            assert "version" in descendant
            assert "creation_date" in descendant
            # artefact_type is optional
            assert isinstance(descendant["version"], int)

    def test_returns_empty_when_no_descendants(
        self, client_with_service, did_service_no_migrations, sample_uuid_2
    ):
        """Endpoint should return empty list when artefact has no descendants."""
        from app.services.did_service import ArtefactInput

        # Create artefact with no descendants
        artefact = did_service_no_migrations.upsert_artefact(
            ArtefactInput(
                external_uid=sample_uuid_2,
                division="epdw",
                artefact_hash="QmYwAPJzv5CZsnAzt8auVZRn8x5M3kN1p6yZR2oG7wJGDk",
            )
        )

        response = client_with_service.get(f"/didcheck/{artefact.version_uid}/descendants")

        assert response.status_code == 200
        data = response.json()

        assert data["descendants"] == []
        assert data["total_count"] == 0
        assert data["has_more"] is False

    def test_returns_404_when_artefact_not_found(
        self, client_with_service, sample_uuid_2
    ):
        """Endpoint should return 404 for non-existent artefact."""
        response = client_with_service.get(f"/didcheck/{sample_uuid_2}/descendants")

        assert response.status_code == 404

    def test_returns_401_with_wrong_token(
        self, client_with_service, parent_with_descendants
    ):
        """Endpoint should return 401 when provided with an invalid token."""
        response = client_with_service.get(
            f"/didcheck/{parent_with_descendants['parent_uid']}/descendants",
            headers={"X-API-Token": "wrong-token"}
        )

        assert response.status_code == 401

    def test_returns_422_with_missing_token(
        self, client_with_service, parent_with_descendants
    ):
        """Endpoint should return 422 when authentication token is missing."""
        response = client_with_service.raw.get(
            f"/didcheck/{parent_with_descendants['parent_uid']}/descendants"
        )

        assert response.status_code == 422

    def test_page_size_max_enforced(
        self, client_with_service, parent_with_descendants
    ):
        """Endpoint should reject page_size > 100."""
        response = client_with_service.get(
            f"/didcheck/{parent_with_descendants['parent_uid']}/descendants?page_size=101"
        )

        assert response.status_code == 422
        assert "Page size must be between 1 and 100" in response.json()["detail"]

    def test_page_minimum_enforced(
        self, client_with_service, parent_with_descendants
    ):
        """Endpoint should reject page < 1."""
        response = client_with_service.get(
            f"/didcheck/{parent_with_descendants['parent_uid']}/descendants?page=0"
        )

        assert response.status_code == 422
        assert "Page must be >= 1" in response.json()["detail"]

    def test_descendants_sorted_by_creation_date(
        self, client_with_service, parent_with_descendants
    ):
        """Descendants should be sorted by creation date (newest first)."""
        response = client_with_service.get(
            f"/didcheck/{parent_with_descendants['parent_uid']}/descendants"
        )

        assert response.status_code == 200
        data = response.json()

        # Descendants should be sorted newest first
        # Created with dates 2026-02-05, 04, 03, 02, 01
        dates = [d["creation_date"] for d in data["descendants"]]
        # Verify they're in descending order
        assert dates == sorted(dates, reverse=True)

    def test_works_with_external_uid(
        self, client_with_service, parent_with_descendants
    ):
        """Endpoint should work with external_uid as well as version_uid."""
        response = client_with_service.get(
            f"/didcheck/{parent_with_descendants['parent_external_uid']}/descendants"
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total_count"] == 5
