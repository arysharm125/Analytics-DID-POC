"""
Reusable dependencies for FastAPI routes.
"""
from fastapi import Header, HTTPException, Depends
from typing import Annotated, Callable, Awaitable
from app.constants import (
    EPDW_ACCESS_TOKEN,
    ADVISORY_ACCESS_TOKEN,
    EXAMPLE_API_TOKEN,
)
import secrets


def create_token_verifier(
    expected_token: str, token_name: str = "API"
) -> Callable[[str], Awaitable[str]]:
    """
    Factory function to create token verification dependencies.

    Args:
        expected_token: The token value to validate against
        token_name: Human-readable name for error messages (e.g., "EPDW", "Advisory")

    Returns:
        An async dependency function that validates the X-API-Token header
    """

    async def verify_token(
        x_api_token: str = Header(
            ...,
            description=f"{token_name} API access token required for authentication.",
            example=EXAMPLE_API_TOKEN,
            alias="X-API-Token",
        )
    ) -> str:
        """
        Dependency that validates the API token from the request header.

        Raises:
            HTTPException: 401 if token is missing or invalid

        Returns:
            The validated token string
        """
        if not secrets.compare_digest(x_api_token, expected_token):
            raise HTTPException(status_code=401, detail=f"Invalid {token_name} token")
        return x_api_token

    return verify_token

# EPDW-specific token dependency
EPDWTokenDep = Annotated[str, Depends(create_token_verifier(EPDW_ACCESS_TOKEN, "EPDW"))]

# Advisory-specific token dependency
AdvisoryTokenDep = Annotated[
    str, Depends(create_token_verifier(ADVISORY_ACCESS_TOKEN, "Advisory"))
]

# Response documentation for token dependencies.
APITokenDep401Response = {401: {"description": "Invalid or missing API token"}}
