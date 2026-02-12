"""
Reusable dependencies for FastAPI routes.
"""
from fastapi import Header, HTTPException, Depends
from typing import Annotated
from app.constants import API_ACCESS_TOKEN, EXAMPLE_API_TOKEN
import secrets


async def verify_api_token(
    x_api_token: str = Header(
        ...,
        description="API access token required for authentication. Must match the configured API_ACCESS_TOKEN.",
        example=EXAMPLE_API_TOKEN,
        alias="X-API-Token",  # This allows both x_api_token and X-API-Token headers
    )
) -> str:
    """
    Dependency that validates the API token from the request header.

    Include APITokenDep401Response as response in the responses= member of the
    router annotation to document the possible response.

    Raises:
        HTTPException: 401 if token is missing or invalid

    Returns:
        The validated token string
    """
    if not secrets.compare_digest(x_api_token, API_ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid API token")
    return x_api_token


# Type alias for cleaner route signatures
APITokenDep = Annotated[str, Depends(verify_api_token)]

# Response documentation for APITokenDep.
APITokenDep401Response = {
    401: {"description": "Invalid or missing API token"}
}
