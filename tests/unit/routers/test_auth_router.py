"""Unit tests for app/routers/auth.py."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.app_factory import create_app
from app.config import AppConfig, AuthConfig, override_config
from app.constants import LOGIN_MODE_CS, LOGIN_MODE_MOCK


@pytest.fixture
def client(test_config, override_test_config):
    """Create FastAPI test client with test config."""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def mock_mode_config(test_config):
    """Create config with mock login mode."""
    return AppConfig(
        vault=test_config.vault,
        tokens=test_config.tokens,
        mongo_pool=test_config.mongo_pool,
        features=test_config.features,
        auth=AuthConfig(
            login_mode=LOGIN_MODE_MOCK,
            cs_api_url="",
            cs_login_url="",
            mock_jwt_secret="test-jwt-secret-min-32-bytes-length",
            token_expiry_minutes=60,
        ),
        expose_error_details=True,
    )


@pytest.fixture
def cs_mode_config(test_config):
    """Create config with CS login mode."""
    return AppConfig(
        vault=test_config.vault,
        tokens=test_config.tokens,
        mongo_pool=test_config.mongo_pool,
        features=test_config.features,
        auth=AuthConfig(
            login_mode=LOGIN_MODE_CS,
            cs_api_url="https://dev.epycadvisory.amd.com/csapi",
            cs_login_url="https://dev.epycadvisory.amd.com",
            mock_jwt_secret="",
            token_expiry_minutes=60,
        ),
        expose_error_details=True,
    )


# =============================================================================
# GET /auth/config
# =============================================================================


class TestGetAuthConfig:
    """Tests for GET /auth/config endpoint."""

    def test_returns_mock_mode_config(self, client, mock_mode_config):
        """Returns correct config for mock mode."""
        override_config(mock_mode_config)

        response = client.get("/auth/config")

        assert response.status_code == 200
        data = response.json()
        assert data["login_mode"] == LOGIN_MODE_MOCK
        assert data["cs_login_url"] is None

    def test_returns_cs_mode_config(self, client, cs_mode_config):
        """Returns correct config for CS mode."""
        override_config(cs_mode_config)

        response = client.get("/auth/config")

        assert response.status_code == 200
        data = response.json()
        assert data["login_mode"] == LOGIN_MODE_CS
        assert data["cs_login_url"] == "https://dev.epycadvisory.amd.com"

    def test_config_endpoint_requires_no_authentication(self, client):
        """Config endpoint should be public (no auth required)."""
        # No auth headers provided
        response = client.get("/auth/config")

        # Should still succeed
        assert response.status_code == 200


# =============================================================================
# POST /auth/login
# =============================================================================


class TestMockLogin:
    """Tests for POST /auth/login endpoint."""

    def test_valid_amd_email_returns_token(self, client, mock_mode_config):
        """Valid @amd.com email returns token and sets cookie."""
        override_config(mock_mode_config)

        response = client.post(
            "/auth/login",
            json={"email": "testuser@amd.com", "password": "anypassword"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 3600  # 60 minutes * 60 seconds

        # Verify cookie is set
        assert "jwt_token" in response.cookies
        assert response.cookies["jwt_token"] == data["access_token"]

    def test_valid_infobellit_email_returns_token(self, client, mock_mode_config):
        """Valid @infobellit.com email returns token."""
        override_config(mock_mode_config)

        response = client.post(
            "/auth/login",
            json={"email": "testuser@infobellit.com", "password": "anypassword"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    def test_invalid_email_domain_returns_401(self, client, mock_mode_config):
        """Email with invalid domain returns 401."""
        override_config(mock_mode_config)

        response = client.post(
            "/auth/login",
            json={"email": "testuser@gmail.com", "password": "password"}
        )

        assert response.status_code == 401
        data = response.json()
        assert "Invalid email domain" in data["detail"]

    def test_cs_mode_returns_404(self, client, cs_mode_config):
        """Login endpoint returns 404 in CS mode."""
        override_config(cs_mode_config)

        response = client.post(
            "/auth/login",
            json={"email": "testuser@amd.com", "password": "password"}
        )

        assert response.status_code == 404
        data = response.json()
        assert "Mock login not available in CS mode" in data["detail"]

    def test_cookie_has_correct_attributes(self, client, mock_mode_config):
        """Cookie is set with correct security attributes."""
        override_config(mock_mode_config)

        response = client.post(
            "/auth/login",
            json={"email": "testuser@amd.com", "password": "password"}
        )

        assert response.status_code == 200

        # Check cookie attributes
        cookie_header = response.headers.get("set-cookie")
        assert cookie_header is not None
        assert "jwt_token=" in cookie_header
        assert "Path=/" in cookie_header
        assert "samesite=lax" in cookie_header.lower()
        # HttpOnly should NOT be set (needs to be readable by JavaScript)
        assert "HttpOnly" not in cookie_header

    def test_accepts_any_password(self, client, mock_mode_config):
        """Mock mode accepts any password for valid email."""
        override_config(mock_mode_config)

        # Try different passwords
        for password in ["test", "", "very-long-password-123456789"]:
            response = client.post(
                "/auth/login",
                json={"email": "testuser@amd.com", "password": password}
            )
            assert response.status_code == 200

    def test_invalid_email_format_returns_422(self, client, mock_mode_config):
        """Invalid email format returns 422 validation error."""
        override_config(mock_mode_config)

        response = client.post(
            "/auth/login",
            json={"email": "not-an-email", "password": "password"}
        )

        assert response.status_code == 422  # Pydantic validation error

    def test_missing_email_returns_422(self, client, mock_mode_config):
        """Missing email field returns 422 validation error."""
        override_config(mock_mode_config)

        response = client.post(
            "/auth/login",
            json={"password": "password"}
        )

        assert response.status_code == 422

    def test_missing_password_returns_422(self, client, mock_mode_config):
        """Missing password field returns 422 validation error."""
        override_config(mock_mode_config)

        response = client.post(
            "/auth/login",
            json={"email": "testuser@amd.com"}
        )

        assert response.status_code == 422

    def test_token_can_be_validated(self, client, mock_mode_config):
        """Returned token can be validated by AuthService."""
        from app.services.auth_service import AuthService

        override_config(mock_mode_config)
        auth_service = AuthService(mock_mode_config.auth)

        # Login
        response = client.post(
            "/auth/login",
            json={"email": "testuser@amd.com", "password": "password"}
        )

        assert response.status_code == 200
        token = response.json()["access_token"]

        # Validate token
        import asyncio
        user_info = asyncio.run(auth_service.validate_token(token))

        assert user_info is not None
        assert user_info.email == "testuser@amd.com"
