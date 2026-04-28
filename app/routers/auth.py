"""Authentication router for mock login and config endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr

from app.config import get_config
from app.constants import LOGIN_MODE_MOCK
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


# =============================================================================
# Request/Response Models
# =============================================================================


class LoginRequest(BaseModel):
    """Login request for mock mode."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Token response from login."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class AuthConfigResponse(BaseModel):
    """Authentication configuration response."""

    login_mode: str  # "cs" or "mock"
    cs_login_url: str | None  # Only for CS mode


# =============================================================================
# Dependencies
# =============================================================================


def get_auth_service() -> AuthService:
    """Get AuthService instance based on current config."""
    config = get_config()
    return AuthService(config.auth)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/config", response_model=AuthConfigResponse)
def get_auth_config() -> AuthConfigResponse:
    """Get authentication configuration for frontend.

    Returns login mode and CS login URL if in CS mode.
    This endpoint is available in both mock and CS modes.
    """
    config = get_config()

    return AuthConfigResponse(
        login_mode=config.auth.login_mode,
        cs_login_url=config.auth.cs_login_url if config.auth.login_mode == "cs" else None,
    )


@router.post("/login", response_model=TokenResponse)
def mock_login(
    credentials: LoginRequest,
    auth_service: AuthServiceDep,
    response: Response,
) -> TokenResponse:
    """Mock login endpoint for local development.

    Only available when LOGIN_MODE=mock.
    Accepts any @amd.com or @infobellit.com email with any password.
    Returns a mock JWT valid for the configured expiry time.
    Sets jwt_token cookie in response (mimics production SSO behavior).

    Args:
        credentials: Login credentials (email and password)
        auth_service: Auth service dependency
        response: FastAPI Response object to set cookies

    Returns:
        TokenResponse with access token

    Raises:
        HTTPException: 404 if not in mock mode, 401 if invalid credentials
    """
    config = get_config()

    # Only available in mock mode
    if config.auth.login_mode != LOGIN_MODE_MOCK:
        raise HTTPException(
            status_code=404,
            detail="Mock login not available in CS mode",
        )

    # Validate email domain
    email_lower = credentials.email.lower()
    if not (email_lower.endswith("@amd.com") or email_lower.endswith("@infobellit.com")):
        raise HTTPException(
            status_code=401,
            detail="Invalid email domain. Only @amd.com and @infobellit.com are allowed.",
        )

    # Create mock JWT
    access_token = auth_service.create_mock_jwt(credentials.email)

    # Set cookie (mimics production SSO behavior)
    # Domain is not set for local development, will be set for production via nginx/proxy
    response.set_cookie(
        key="jwt_token",
        value=access_token,
        httponly=False,  # Needs to be readable by JavaScript for frontend auth store
        samesite="lax",
        path="/",
        max_age=config.auth.token_expiry_minutes * 60,
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=config.auth.token_expiry_minutes * 60,
    )
