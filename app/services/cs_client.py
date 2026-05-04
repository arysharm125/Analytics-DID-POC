"""HTTP client for Common Services API."""

import logging

import httpx
from pydantic import ValidationError as PydanticValidationError

from app.services.auth_types import CSResponse
from app.services.exceptions import CSResponseParseError

logger = logging.getLogger("did_vault_api_sut")


class CSClient:
    """HTTP client for Common Services API.

    Handles communication with the CS getUserToken endpoint for user validation.
    """

    def __init__(self, base_url: str):
        """Initialize CS client.

        Args:
            base_url: CS API base URL (e.g., https://dev.epycadvisory.amd.com/csapi)
        """
        self.base_url = base_url.rstrip("/")

    async def get_user_token(
        self, bearer_token: str, application: str = "DIDCHECK"
    ) -> CSResponse:
        """Validate bearer token with CS API.

        Args:
            bearer_token: The bearer token to validate
            application: Application name (default: "DIDCHECK")

        Returns:
            CSResponse with user data and permissions

        Raises:
            httpx.HTTPError: If the request fails
            ValueError: If the response cannot be parsed
        """
        url = f"{self.base_url}/getUserToken"

        async with httpx.AsyncClient() as client:
            logger.debug(f"Calling CS API: {url}")

            response = await client.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "accessToken": f"Bearer {bearer_token}",
                },
                json={"application": application},
                timeout=10.0,
            )

            response.raise_for_status()

            # Parse and validate response
            data = response.json()
            try:
                return CSResponse.model_validate(data)
            except PydanticValidationError as e:
                raise CSResponseParseError(str(e)) from e
