"""Authentication types and models for CS API integration."""

from pydantic import BaseModel

# =============================================================================
# CS API Response Models
# =============================================================================


class CSUserData(BaseModel):
    """User data from CS API."""

    userEmail: str  # noqa: N815
    firstName: str  # noqa: N815
    lastName: str  # noqa: N815
    country: str
    org: str


class CSEndpoint(BaseModel):
    """Endpoint permission from CS API."""

    id: int
    name: str
    enabled: bool


class CSFeature(BaseModel):
    """Feature permission from CS API."""

    id: int
    name: str
    enabled: bool
    endpoints: list[CSEndpoint]


class CSDIDCheckRole(BaseModel):
    """DIDCheck role and permissions from CS API."""

    role_id: int
    role_name: str
    features: list[CSFeature]


class CSFeaturesData(BaseModel):
    """Features data from CS API."""

    DIDCheck: CSDIDCheckRole


class CSData(BaseModel):
    """Data object from CS API response."""

    UserData: CSUserData
    FeaturesData: CSFeaturesData


class CSResponse(BaseModel):
    """Complete response from CS /csapi/getUserToken endpoint."""

    message: str
    Data: CSData
    errorCode: int  # noqa: N815


# =============================================================================
# Internal User Info Model
# =============================================================================


class UserInfo(BaseModel):
    """Simplified user information for internal use."""

    email: str
    first_name: str
    last_name: str
    org: str
    role_name: str
    role_id: int

    @classmethod
    def from_cs_response(cls, cs_response: CSResponse) -> "UserInfo":
        """Create UserInfo from CS API response.

        Args:
            cs_response: The response from CS API

        Returns:
            UserInfo instance

        Raises:
            ValueError: If CS response indicates error
        """
        if cs_response.errorCode != 1:
            raise ValueError(f"CS API error: {cs_response.message}")

        return cls(
            email=cs_response.Data.UserData.userEmail,
            first_name=cs_response.Data.UserData.firstName,
            last_name=cs_response.Data.UserData.lastName,
            org=cs_response.Data.UserData.org,
            role_name=cs_response.Data.FeaturesData.DIDCheck.role_name,
            role_id=cs_response.Data.FeaturesData.DIDCheck.role_id,
        )

    @classmethod
    def from_mock_jwt_claims(cls, claims: dict) -> "UserInfo":
        """Create UserInfo from mock JWT claims.

        Args:
            claims: JWT payload claims

        Returns:
            UserInfo instance
        """
        return cls(
            email=claims.get("sub", ""),
            first_name=claims.get("first_name", ""),
            last_name=claims.get("last_name", ""),
            org=claims.get("org", ""),
            role_name=claims.get("role_name", "mock_user"),
            role_id=claims.get("role_id", 0),
        )
