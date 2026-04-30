"""Authentication service for both CS and mock modes."""

import logging
from datetime import datetime, timedelta, timezone

import jwt

from app.config import AuthConfig
from app.constants import LOGIN_MODE_CS, LOGIN_MODE_MOCK
from app.services.auth_types import UserInfo
from app.services.cs_client import CSClient

logger = logging.getLogger("did_vault_api_sut")


class AuthService:
    """Handles authentication for both CS and mock modes."""

    def __init__(self, config: AuthConfig):
        """Initialize auth service.

        Args:
            config: Authentication configuration
        """
        self.config = config
        self.cs_client = CSClient(config.cs_api_url) if config.login_mode == LOGIN_MODE_CS else None

    async def validate_token(self, bearer_token: str) -> UserInfo | None:
        """Validate bearer token based on login mode.

        Args:
            bearer_token: The bearer token to validate

        Returns:
            UserInfo if token is valid, None otherwise

        Raises:
            ValueError: If login_mode is not supported
        """
        if self.config.login_mode == LOGIN_MODE_MOCK:
            return self._validate_mock_jwt(bearer_token)
        elif self.config.login_mode == LOGIN_MODE_CS:
            return await self._validate_cs_token(bearer_token)
        else:
            raise ValueError(
                f"Unsupported login_mode: '{self.config.login_mode}'. "
                f"Must be one of: {LOGIN_MODE_MOCK}, {LOGIN_MODE_CS}"
            )

    async def _validate_cs_token(self, token: str) -> UserInfo | None:
        """Call CS API to validate token and get user info.

        Args:
            token: The bearer token to validate

        Returns:
            UserInfo if valid, None otherwise
        """
        if not self.cs_client:
            logger.error("CS client not initialized but in CS mode")
            return None

        try:
            cs_response = await self.cs_client.get_user_token(token, "DIDCHECK")
            return UserInfo.from_cs_response(cs_response)
        except Exception as e:
            logger.warning(f"CS token validation failed: {e}")
            return None

    def _validate_mock_jwt(self, token: str) -> UserInfo | None:
        """Validate a mock JWT and extract user info.

        Args:
            token: The JWT to validate

        Returns:
            UserInfo if valid, None otherwise
        """
        try:
            # Decode and verify JWT
            claims = jwt.decode(
                token,
                self.config.mock_jwt_secret,
                algorithms=["HS256"],
            )

            # Extract user info from claims
            return UserInfo.from_mock_jwt_claims(claims)

        except jwt.ExpiredSignatureError:
            logger.debug("Mock JWT has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.debug(f"Invalid mock JWT: {e}")
            return None

    def create_mock_jwt(self, email: str) -> str:
        """Create a mock JWT for development.

        Args:
            email: User email address

        Returns:
            Signed JWT string
        """
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(minutes=self.config.token_expiry_minutes)

        # Extract org from email domain
        org = email.split("@")[1].split(".")[0] if "@" in email else "unknown"

        # Extract first name from email (before @)
        first_name = email.split("@")[0] if "@" in email else email

        claims = {
            "sub": email,  # Subject (user identifier)
            "first_name": first_name,
            "last_name": "",
            "org": org,
            "role_name": "mock_user",
            "role_id": 0,
            "iat": now,  # Issued at
            "exp": expiry,  # Expiration
        }

        return jwt.encode(claims, self.config.mock_jwt_secret, algorithm="HS256")
