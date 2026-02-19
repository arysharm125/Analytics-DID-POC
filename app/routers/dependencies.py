"""
Reusable dependencies for FastAPI routes.
"""

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.config import get_config
from app.constants import EXAMPLE_API_TOKEN


async def verify_epdw_token(
    x_api_token: str = Header(
        ...,
        description="EPDW API access token required for authentication.",
        example=EXAMPLE_API_TOKEN,
        alias="X-API-Token",
    )
) -> str:
    """
    Dependency that validates the EPDW API token from the request header.

    Uses lazy config loading to allow test overrides.

    Raises:
        HTTPException: 401 if token is missing or invalid

    Returns:
        The validated token string
    """
    config = get_config()
    if not secrets.compare_digest(x_api_token, config.tokens.epdw_access_token):
        raise HTTPException(status_code=401, detail="Invalid EPDW token")
    return x_api_token


async def verify_advisory_token(
    x_api_token: str = Header(
        ...,
        description="Advisory API access token required for authentication.",
        example=EXAMPLE_API_TOKEN,
        alias="X-API-Token",
    )
) -> str:
    """
    Dependency that validates the Advisory API token from the request header.

    Uses lazy config loading to allow test overrides.

    Raises:
        HTTPException: 401 if token is missing or invalid

    Returns:
        The validated token string
    """
    config = get_config()
    if not secrets.compare_digest(x_api_token, config.tokens.advisory_access_token):
        raise HTTPException(status_code=401, detail="Invalid Advisory token")
    return x_api_token


# EPDW-specific token dependency
EPDWTokenDep = Annotated[str, Depends(verify_epdw_token)]

# Advisory-specific token dependency
AdvisoryTokenDep = Annotated[str, Depends(verify_advisory_token)]

# Response documentation for token dependencies.
APITokenDep401Response = {401: {"description": "Invalid or missing API token"}}
