"""Application configuration with lazy loading and test override support."""

import os
import secrets
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

from app.constants import LOGIN_MODE_CS, LOGIN_MODE_MOCK


@dataclass(frozen=True)
class VaultConfig:
    """Vault connection configuration."""

    addr: str
    token: str
    mount: str
    local_mock_path: str  # Empty string = use real vault


@dataclass(frozen=True)
class TokenConfig:
    """API token configuration."""

    epdw_access_token: str
    advisory_access_token: str
    didcheck_access_token: str
    demodiv_access_token: str


@dataclass(frozen=True)
class MongoPoolConfig:
    """MongoDB connection pool configuration."""

    max_pool_size: int
    min_pool_size: int
    max_idle_time_ms: int
    wait_queue_timeout_ms: int
    pool_monitor_interval_s: int


@dataclass(frozen=True)
class MongoCollectionConfig:
    """MongoDB collection names."""

    qa_benchmark_collection: str
    qa_benchmark_iterations: str


@dataclass(frozen=True)
class FeatureFlags:
    """Feature flag configuration."""

    didcheck_router: bool
    demodiv_router: bool
    docs_router: bool
    debug_vc_nquads: bool


@dataclass(frozen=True)
class AuthConfig:
    """Authentication configuration."""

    login_mode: str  # "cs" or "mock"
    cs_api_url: str  # CS API base URL (e.g., https://dev.epycadvisory.amd.com/csapi)
    cs_login_url: str  # CS login page URL (e.g., https://dev.epycadvisory.amd.com)
    mock_jwt_secret: str  # Secret for signing mock JWTs (auto-generated if empty)
    token_expiry_minutes: int  # JWT expiry time in minutes


@dataclass(frozen=True)
class AppConfig:
    """Root application configuration."""

    vault: VaultConfig
    tokens: TokenConfig
    mongo_pool: MongoPoolConfig
    features: FeatureFlags
    auth: AuthConfig
    expose_error_details: bool


def _load_config_from_env() -> AppConfig:
    """Load configuration from environment variables.

    Calls load_dotenv() to ensure .env file is loaded.

    Raises:
        ValueError: If LOGIN_MODE is not one of the supported values
    """
    load_dotenv(verbose=True)

    # Validate login mode
    login_mode = os.getenv("LOGIN_MODE", LOGIN_MODE_MOCK)
    if login_mode not in (LOGIN_MODE_MOCK, LOGIN_MODE_CS):
        raise ValueError(
            f"Invalid LOGIN_MODE: '{login_mode}'. "
            f"Must be one of: {LOGIN_MODE_MOCK}, {LOGIN_MODE_CS}"
        )

    # Auto-generate mock JWT secret if not provided
    mock_jwt_secret = os.getenv("MOCK_JWT_SECRET", "")
    if not mock_jwt_secret:
        # Generate a secure random secret (32 bytes = 256 bits)
        mock_jwt_secret = secrets.token_urlsafe(32)

    return AppConfig(
        vault=VaultConfig(
            addr=os.getenv("VAULT_ADDR", ""),
            token=os.getenv("VAULT_TOKEN", ""),
            mount=os.getenv("VAULT_MOUNT", "secret"),
            local_mock_path=os.getenv("VAULT_LOCAL_MOCK", ""),
        ),
        tokens=TokenConfig(
            epdw_access_token=os.getenv("EPDW_ACCESS_TOKEN", ""),
            advisory_access_token=os.getenv("ADVISORY_ACCESS_TOKEN", ""),
            didcheck_access_token=os.getenv("DIDCHECK_ACCESS_TOKEN", ""),
            demodiv_access_token=os.getenv("DEMODIV_ACCESS_TOKEN", ""),
        ),
        mongo_pool=MongoPoolConfig(
            max_pool_size=int(os.getenv("MONGO_MAX_POOL_SIZE", "100")),
            min_pool_size=int(os.getenv("MONGO_MIN_POOL_SIZE", "5")),
            max_idle_time_ms=int(os.getenv("MONGO_MAX_IDLE_TIME_MS", "30000")),
            wait_queue_timeout_ms=int(os.getenv("MONGO_WAIT_QUEUE_TIMEOUT_MS", "5000")),
            pool_monitor_interval_s=int(os.getenv("MONGO_POOL_MONITOR_INTERVAL", "60")),
        ),
        features=FeatureFlags(
            didcheck_router=bool(os.getenv("FEATURE_DIDCHECK_ROUTER", "")),
            demodiv_router=bool(os.getenv("FEATURE_DEMODIV_ROUTER", "")),
            docs_router=bool(os.getenv("FEATURE_DOCS_ROUTER", "")),
            debug_vc_nquads=bool(os.getenv("FEATURE_DEBUG_VC_NQUADS", "")),
        ),
        auth=AuthConfig(
            login_mode=login_mode,
            cs_api_url=os.getenv("CS_API_URL", ""),
            cs_login_url=os.getenv("CS_LOGIN_URL", ""),
            mock_jwt_secret=mock_jwt_secret,
            token_expiry_minutes=int(os.getenv("TOKEN_EXPIRY_MINUTES", "60")),
        ),
        expose_error_details=bool(os.getenv("EXPOSE_ERROR_DETAILS", "")),
    )


# Storage for test override
_config_override: AppConfig | None = None


def get_config() -> AppConfig:
    """Get application configuration.

    Returns the test override if set, otherwise loads from environment.
    This is NOT cached when an override is set, allowing tests to change
    configuration between test cases.

    Returns:
        The current application configuration.
    """
    if _config_override is not None:
        return _config_override
    return _get_cached_config()


@lru_cache(maxsize=1)
def _get_cached_config() -> AppConfig:
    """Cached config loader for production use."""
    return _load_config_from_env()


def override_config(config: AppConfig | None) -> None:
    """Override configuration for testing.

    Args:
        config: The configuration to use, or None to clear override.

    Example:
        # In test setup
        override_config(AppConfig(...))

        # In test teardown
        override_config(None)
    """
    global _config_override
    _config_override = config


def reset_config_cache() -> None:
    """Clear the cached configuration.

    Use this if environment variables have changed and you need
    to reload configuration.
    """
    _get_cached_config.cache_clear()
