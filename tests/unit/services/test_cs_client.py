"""Unit tests for app/services/cs_client.py.

Tests the CSClient class methods using mocked httpx.AsyncClient for isolation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.cs_client import CSClient
from app.services.exceptions import CSResponseParseError


@pytest.fixture
def cs_client():
    """Create a CSClient instance."""
    return CSClient(base_url="https://test.example.com/csapi")


@pytest.fixture
def valid_cs_response():
    """Valid CS API response structure."""
    return {
        "message": "success",
        "errorCode": 1,
        "Data": {
            "UserData": {
                "userEmail": "test.user@amd.com",
                "firstName": "Test",
                "lastName": "User",
                "country": "US",
                "org": "TestOrg",
            },
            "FeaturesData": {
                "DIDCheck": {
                    "role_id": 1,
                    "role_name": "admin",
                    "features": [],
                }
            },
        },
    }


class TestGetUserToken:
    """Tests for get_user_token method."""

    @pytest.mark.asyncio
    async def test_get_user_token_success_200(self, cs_client, valid_cs_response):
        """Getting user token with valid 200 response should return CSResponse."""
        # Create a mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = valid_cs_response
        mock_response.raise_for_status = MagicMock()

        # Mock the AsyncClient context manager and post method
        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_async_client

            result = await cs_client.get_user_token("test-bearer-token")

            # Verify the response is properly parsed
            assert result.message == "success"
            assert result.errorCode == 1
            assert result.Data.UserData.userEmail == "test.user@amd.com"
            assert result.Data.UserData.firstName == "Test"
            assert result.Data.FeaturesData.DIDCheck.role_name == "admin"

            # Verify the correct API call was made
            mock_async_client.post.assert_called_once()
            call_args = mock_async_client.post.call_args
            assert call_args[0][0] == "https://test.example.com/csapi/getUserToken"
            assert call_args[1]["headers"]["accessToken"] == "Bearer test-bearer-token"
            assert call_args[1]["json"]["application"] == "DIDCHECK"

    @pytest.mark.asyncio
    async def test_get_user_token_custom_application(self, cs_client, valid_cs_response):
        """Getting user token with custom application name should use that name."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = valid_cs_response
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_async_client

            await cs_client.get_user_token("test-bearer-token", application="CUSTOM_APP")

            call_args = mock_async_client.post.call_args
            assert call_args[1]["json"]["application"] == "CUSTOM_APP"

    @pytest.mark.asyncio
    async def test_get_user_token_401_raises_http_error(self, cs_client):
        """Getting user token with 401 response should raise httpx.HTTPStatusError."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Unauthorized", request=MagicMock(), response=mock_response
        )

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_async_client

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await cs_client.get_user_token("invalid-token")

            assert exc_info.value.response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_user_token_500_raises_http_error(self, cs_client):
        """Getting user token with 500 response should raise httpx.HTTPStatusError."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Internal Server Error", request=MagicMock(), response=mock_response
        )

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_async_client

            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await cs_client.get_user_token("test-token")

            assert exc_info.value.response.status_code == 500

    @pytest.mark.asyncio
    async def test_get_user_token_malformed_json_raises_parse_error(self, cs_client):
        """Getting user token with malformed JSON structure should raise CSResponseParseError."""
        # Response missing required Data field
        malformed_response = {
            "message": "success",
            "errorCode": 1,
            # Missing "Data" field entirely
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = malformed_response
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_async_client

            with pytest.raises(CSResponseParseError) as exc_info:
                await cs_client.get_user_token("test-token")

            assert exc_info.value.status_code == 500
            assert "Failed to parse CS API response" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_user_token_missing_user_email_raises_parse_error(self, cs_client):
        """Getting user token missing UserData.userEmail should raise CSResponseParseError."""
        response_missing_email = {
            "message": "success",
            "errorCode": 1,
            "Data": {
                "UserData": {
                    # Missing "userEmail" field
                    "firstName": "Test",
                    "lastName": "User",
                    "country": "US",
                    "org": "TestOrg",
                },
                "FeaturesData": {
                    "DIDCheck": {
                        "role_id": 1,
                        "role_name": "admin",
                        "features": [],
                    }
                },
            },
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_missing_email
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_async_client

            with pytest.raises(CSResponseParseError) as exc_info:
                await cs_client.get_user_token("test-token")

            assert exc_info.value.status_code == 500
            assert "Failed to parse CS API response" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_user_token_missing_role_name_raises_parse_error(self, cs_client):
        """Getting user token missing FeaturesData.DIDCheck.role_name should raise CSResponseParseError."""
        response_missing_role_name = {
            "message": "success",
            "errorCode": 1,
            "Data": {
                "UserData": {
                    "userEmail": "test.user@amd.com",
                    "firstName": "Test",
                    "lastName": "User",
                    "country": "US",
                    "org": "TestOrg",
                },
                "FeaturesData": {
                    "DIDCheck": {
                        "role_id": 1,
                        # Missing "role_name" field
                        "features": [],
                    }
                },
            },
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_missing_role_name
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_async_client

            with pytest.raises(CSResponseParseError) as exc_info:
                await cs_client.get_user_token("test-token")

            assert exc_info.value.status_code == 500
            assert "Failed to parse CS API response" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_user_token_missing_features_data_raises_parse_error(self, cs_client):
        """Getting user token missing FeaturesData should raise CSResponseParseError."""
        response_missing_features = {
            "message": "success",
            "errorCode": 1,
            "Data": {
                "UserData": {
                    "userEmail": "test.user@amd.com",
                    "firstName": "Test",
                    "lastName": "User",
                    "country": "US",
                    "org": "TestOrg",
                },
                # Missing "FeaturesData" field
            },
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response_missing_features
        mock_response.raise_for_status = MagicMock()

        mock_async_client = AsyncMock()
        mock_async_client.post.return_value = mock_response

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.return_value = mock_async_client

            with pytest.raises(CSResponseParseError) as exc_info:
                await cs_client.get_user_token("test-token")

            assert exc_info.value.status_code == 500
            assert "Failed to parse CS API response" in exc_info.value.detail
