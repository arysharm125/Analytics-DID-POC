"""Unit tests for app/services/auth_service.py.

Tests the AuthService validation routing logic.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import AuthConfig
from app.constants import LOGIN_MODE_CS, LOGIN_MODE_MOCK
from app.services.auth_service import AuthService
from app.services.auth_types import UserInfo


@pytest.fixture
def mock_config():
    """Create a mock AuthConfig."""
    config = MagicMock(spec=AuthConfig)
    config.cs_api_url = "https://test.example.com/csapi"
    config.mock_jwt_secret = "test-jwt-secret-min-32-bytes-length"
    config.token_expiry_minutes = 60
    return config


@pytest.fixture
def mock_user_info():
    """Create a mock UserInfo for testing."""
    return UserInfo(
        email="test.user@amd.com",
        first_name="Test",
        last_name="User",
        org="TestOrg",
        role_name="admin",
        role_id=1,
    )


class TestValidateTokenRouting:
    """Tests for validate_token method routing logic."""

    @pytest.mark.asyncio
    async def test_validate_token_calls_mock_jwt_when_mode_is_mock(
        self, mock_config, mock_user_info
    ):
        """validate_token should call _validate_mock_jwt when login_mode is MOCK."""
        mock_config.login_mode = LOGIN_MODE_MOCK
        auth_service = AuthService(mock_config)

        # Mock the _validate_mock_jwt method
        with patch.object(
            auth_service, "_validate_mock_jwt", return_value=mock_user_info
        ) as mock_validate:
            result = await auth_service.validate_token("test-token")

            # Verify _validate_mock_jwt was called with the correct token
            mock_validate.assert_called_once_with("test-token")

            # Verify the result is from _validate_mock_jwt
            assert result == mock_user_info

    @pytest.mark.asyncio
    async def test_validate_token_calls_cs_token_when_mode_is_cs(
        self, mock_config, mock_user_info
    ):
        """validate_token should call _validate_cs_token when login_mode is CS."""
        mock_config.login_mode = LOGIN_MODE_CS
        auth_service = AuthService(mock_config)

        # Mock the _validate_cs_token method
        with patch.object(
            auth_service, "_validate_cs_token", new_callable=AsyncMock, return_value=mock_user_info
        ) as mock_validate:
            result = await auth_service.validate_token("test-token")

            # Verify _validate_cs_token was called with the correct token
            mock_validate.assert_called_once_with("test-token")

            # Verify the result is from _validate_cs_token
            assert result == mock_user_info

    @pytest.mark.asyncio
    async def test_validate_token_raises_on_unsupported_mode(self, mock_config):
        """validate_token should raise ValueError when login_mode is unsupported."""
        mock_config.login_mode = "UNSUPPORTED_MODE"
        auth_service = AuthService(mock_config)

        with pytest.raises(ValueError) as exc_info:
            await auth_service.validate_token("test-token")

        assert "Unsupported login_mode" in str(exc_info.value)
        assert "UNSUPPORTED_MODE" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_validate_token_does_not_call_mock_jwt_when_mode_is_cs(
        self, mock_config, mock_user_info
    ):
        """validate_token should NOT call _validate_mock_jwt when login_mode is CS."""
        mock_config.login_mode = LOGIN_MODE_CS
        auth_service = AuthService(mock_config)

        with patch.object(
            auth_service, "_validate_mock_jwt", return_value=mock_user_info
        ) as mock_validate_jwt, patch.object(
            auth_service, "_validate_cs_token", new_callable=AsyncMock, return_value=mock_user_info
        ):
            await auth_service.validate_token("test-token")

            # Verify _validate_mock_jwt was NOT called
            mock_validate_jwt.assert_not_called()

    @pytest.mark.asyncio
    async def test_validate_token_does_not_call_cs_token_when_mode_is_mock(
        self, mock_config, mock_user_info
    ):
        """validate_token should NOT call _validate_cs_token when login_mode is MOCK."""
        mock_config.login_mode = LOGIN_MODE_MOCK
        auth_service = AuthService(mock_config)

        with patch.object(
            auth_service, "_validate_cs_token", new_callable=AsyncMock, return_value=mock_user_info
        ) as mock_validate_cs, patch.object(
            auth_service, "_validate_mock_jwt", return_value=mock_user_info
        ):
            await auth_service.validate_token("test-token")

            # Verify _validate_cs_token was NOT called
            mock_validate_cs.assert_not_called()


class TestCSClientInitialization:
    """Tests for CSClient initialization based on login mode."""

    def test_cs_client_initialized_when_mode_is_cs(self, mock_config):
        """CSClient should be initialized when login_mode is CS."""
        mock_config.login_mode = LOGIN_MODE_CS

        with patch("app.services.auth_service.CSClient") as mock_cs_client_class:
            auth_service = AuthService(mock_config)

            # Verify CSClient was initialized with correct URL
            mock_cs_client_class.assert_called_once_with(mock_config.cs_api_url)

            # Verify cs_client is set
            assert auth_service.cs_client is not None

    def test_cs_client_not_initialized_when_mode_is_mock(self, mock_config):
        """CSClient should NOT be initialized when login_mode is MOCK."""
        mock_config.login_mode = LOGIN_MODE_MOCK

        with patch("app.services.auth_service.CSClient") as mock_cs_client_class:
            auth_service = AuthService(mock_config)

            # Verify CSClient was NOT initialized
            mock_cs_client_class.assert_not_called()

            # Verify cs_client is None
            assert auth_service.cs_client is None


class TestValidateCSToken:
    """Tests for _validate_cs_token method."""

    @pytest.mark.asyncio
    async def test_validate_cs_token_returns_none_when_cs_client_is_none(self, mock_config):
        """_validate_cs_token should return None when cs_client is not initialized."""
        mock_config.login_mode = LOGIN_MODE_CS
        auth_service = AuthService(mock_config)

        # Manually set cs_client to None to simulate initialization failure
        auth_service.cs_client = None

        result = await auth_service._validate_cs_token("test-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_validate_cs_token_success_returns_user_info(self, mock_config, mock_user_info):
        """_validate_cs_token should return UserInfo when CS API call succeeds."""
        mock_config.login_mode = LOGIN_MODE_CS

        # Create a mock CSResponse
        mock_cs_response = MagicMock()

        with patch("app.services.auth_service.CSClient") as mock_cs_client_class:
            mock_cs_client_instance = MagicMock()
            mock_cs_client_instance.get_user_token = AsyncMock(return_value=mock_cs_response)
            mock_cs_client_class.return_value = mock_cs_client_instance

            auth_service = AuthService(mock_config)

            # Mock UserInfo.from_cs_response
            with patch.object(UserInfo, "from_cs_response", return_value=mock_user_info) as mock_from_cs:
                result = await auth_service._validate_cs_token("test-token")

                # Verify get_user_token was called correctly
                mock_cs_client_instance.get_user_token.assert_called_once_with("test-token", "DIDCHECK")

                # Verify from_cs_response was called with the CS response
                mock_from_cs.assert_called_once_with(mock_cs_response)

                # Verify the result is the UserInfo
                assert result == mock_user_info

    @pytest.mark.asyncio
    async def test_validate_cs_token_returns_none_on_exception(self, mock_config):
        """_validate_cs_token should return None when CS API call raises an exception."""
        mock_config.login_mode = LOGIN_MODE_CS

        with patch("app.services.auth_service.CSClient") as mock_cs_client_class:
            mock_cs_client_instance = MagicMock()
            mock_cs_client_instance.get_user_token = AsyncMock(
                side_effect=Exception("CS API error")
            )
            mock_cs_client_class.return_value = mock_cs_client_instance

            auth_service = AuthService(mock_config)

            result = await auth_service._validate_cs_token("test-token")

            # Verify get_user_token was called
            mock_cs_client_instance.get_user_token.assert_called_once_with("test-token", "DIDCHECK")

            # Verify None is returned
            assert result is None

    @pytest.mark.asyncio
    async def test_validate_cs_token_returns_none_when_from_cs_response_raises(self, mock_config):
        """_validate_cs_token should return None when UserInfo.from_cs_response raises an exception."""
        mock_config.login_mode = LOGIN_MODE_CS

        mock_cs_response = MagicMock()

        with patch("app.services.auth_service.CSClient") as mock_cs_client_class:
            mock_cs_client_instance = MagicMock()
            mock_cs_client_instance.get_user_token = AsyncMock(return_value=mock_cs_response)
            mock_cs_client_class.return_value = mock_cs_client_instance

            auth_service = AuthService(mock_config)

            # Mock UserInfo.from_cs_response to raise an exception
            with patch.object(
                UserInfo, "from_cs_response", side_effect=ValueError("Invalid CS response")
            ) as mock_from_cs:
                result = await auth_service._validate_cs_token("test-token")

                # Verify get_user_token was called
                mock_cs_client_instance.get_user_token.assert_called_once_with("test-token", "DIDCHECK")

                # Verify from_cs_response was called
                mock_from_cs.assert_called_once_with(mock_cs_response)

                # Verify None is returned
                assert result is None
