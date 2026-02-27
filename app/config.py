"""Application configuration with lazy loading and test override support."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional
import os

from dotenv import load_dotenv


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


@dataclass(frozen=True)
class MongoCollectionConfig:
    """MongoDB collection names."""

    qa_benchmark_collection: str
    qa_benchmark_iterations: str


@dataclass(frozen=True)
class FeatureFlags:
    """Feature flag configuration."""

    didcheck_router: bool
    debug_vc_nquads: bool


@dataclass(frozen=True)
class AppConfig:
    """Root application configuration."""

    vault: VaultConfig
    tokens: TokenConfig
    collections: MongoCollectionConfig
    features: FeatureFlags
    expose_error_details: bool


def _load_config_from_env() -> AppConfig:
    """Load configuration from environment variables.

    Calls load_dotenv() to ensure .env file is loaded.
    """
    load_dotenv(verbose=True)

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
        ),
        collections=MongoCollectionConfig(
            qa_benchmark_collection=os.getenv(
                "QA_COLLECTION", "benchmark_executions"
            ),
            qa_benchmark_iterations=os.getenv(
                "QA_COLLECTION_ITER", "benchmark_iterations"
            ),
        ),
        features=FeatureFlags(
            didcheck_router=bool(os.getenv("FEATURE_DIDCHECK_ROUTER", "")),
            debug_vc_nquads=bool(os.getenv("FEATURE_DEBUG_VC_NQUADS", "")),
        ),
        expose_error_details=bool(os.getenv("EXPOSE_ERROR_DETAILS", "")),
    )


# Storage for test override
_config_override: Optional[AppConfig] = None


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


def override_config(config: Optional[AppConfig]) -> None:
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
