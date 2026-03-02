"""Shared pytest fixtures for all tests. Automatically loaded by pytest.

IMPORTANT: This conftest properly resets all singletons and caches between tests
to prevent test pollution. The reset order matters:
1. Reset dependencies (dependencies.py caches)
2. Reset vault module singletons (vault.py caches)
3. Reset DIDService singleton
4. Reset config cache
"""

import os
import time
import uuid
from collections.abc import Generator

import pytest

from app.config import (
    AppConfig,
    FeatureFlags,
    MongoCollectionConfig,
    MongoPoolConfig,
    TokenConfig,
    VaultConfig,
    override_config,
    reset_config_cache,
)
from app.database import MongoConnector


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--db-mode",
        action="store",
        default="mock",
        choices=["mock", "container", "real"],
        help="Database backend: mock (mongomock), container (testcontainers), real",
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests when running in mock mode."""
    db_mode = config.getoption("--db-mode")

    if db_mode == "mock":
        skip_integration = pytest.mark.skip(
            reason="Integration tests require --db-mode=container or --db-mode=real"
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


@pytest.fixture(autouse=True)
def reset_singletons():
    """Auto-reset all singletons before and after each test.

    This fixture runs automatically for every test to ensure clean state.
    It resets:
    - FastAPI dependencies (get_db, get_vault in dependencies.py)
    - Vault module singletons (vault.py)
    - DIDService singleton
    - Config cache
    """
    # Reset before test
    _reset_all()
    yield
    # Reset after test
    _reset_all()


def _reset_all():
    """Reset all cached state across the application."""
    # Reset FastAPI dependencies (includes reset_config_cache and DIDService)
    from app.routers.dependencies import reset_all_dependencies

    reset_all_dependencies()

    # Reset vault.py module-level singletons
    from app.services.vault import reset_vault_client, reset_vault_service

    reset_vault_client()
    reset_vault_service()

    # Clear config override
    override_config(None)
    reset_config_cache()


@pytest.fixture(scope="session")
def db_mode(request) -> str:
    """Get the database mode from command line."""
    return request.config.getoption("--db-mode")


@pytest.fixture(scope="session")
def mongodb_container(db_mode):
    """Session-scoped MongoDB container (only for container mode).

    Requires testcontainers package to be installed:
        pip install testcontainers
    """
    if db_mode != "container":
        yield None
        return

    try:
        from testcontainers.mongodb import MongoDbContainer
    except ImportError:
        pytest.skip("testcontainers package not installed")
        return

    container = MongoDbContainer("mongo:6.0")
    container.start()

    # --- Readiness guard ---
    # Even though testcontainers usually waits for the port to be open,
    # give Mongo a moment to become command-ready.
    time.sleep(0.5)

    yield container
    container.stop()


@pytest.fixture
def db_connector(db_mode, mongodb_container) -> Generator[MongoConnector, None, None]:
    """Per-test MongoConnector with isolated database.

    Creates a fresh database for each test to ensure isolation.

    Args:
        db_mode: The database backend mode (mock, container, real)
        mongodb_container: The MongoDB container (only for container mode)

    Yields:
        MongoConnector instance with isolated database
    """
    db_name = f"test_{uuid.uuid4().hex[:8]}"

    if db_mode == "mock":
        import mongomock

        client = mongomock.MongoClient()
        connector = MongoConnector.from_client(client, db_name)

    elif db_mode == "container":
        if mongodb_container is None:
            pytest.skip("MongoDB container not available")
        conn_url = mongodb_container.get_connection_url()
        connector = MongoConnector.from_uri(conn_url, db_name)

    elif db_mode == "real":
        conn_url = os.environ.get("TEST_MONGODB_URI", "mongodb://localhost:27017")
        connector = MongoConnector.from_uri(conn_url, db_name)

    else:
        raise ValueError(f"Unknown db_mode: {db_mode}")


    try:
        yield connector
    finally:
        # Teardown order matters: drop DB, then close client
        try:
            if db_mode != "mock" and connector.client:
                connector.client.drop_database(db_name)
        finally:
            connector.close_connection()



@pytest.fixture
def test_config() -> AppConfig:
    """Create a test configuration with sensible defaults."""
    return AppConfig(
        vault=VaultConfig(
            addr="",
            token="",
            mount="secret",
            local_mock_path="",
        ),
        tokens=TokenConfig(
            epdw_access_token="test-epdw-token",
            advisory_access_token="test-advisory-token",
            didcheck_access_token="test-didcheck-token",
        ),
        collections=MongoCollectionConfig(
            qa_benchmark_collection="test_benchmark_executions",
            qa_benchmark_iterations="test_benchmark_iterations",
        ),
        mongo_pool=MongoPoolConfig(
            max_pool_size=100,
            min_pool_size=5,
            max_idle_time_ms=30000,
            wait_queue_timeout_ms=5000,
            pool_monitor_interval_s=60,
        ),
        features=FeatureFlags(
            didcheck_router=True,
            debug_vc_nquads=True,
        ),
        expose_error_details=True,
    )


@pytest.fixture
def override_test_config(test_config):
    """Override application config for testing.

    Note: reset_singletons autouse fixture handles cleanup, but we
    explicitly clear here for safety.
    """
    override_config(test_config)
    yield test_config
    override_config(None)
    reset_config_cache()


@pytest.fixture
def in_memory_vault():
    """Create an in-memory vault client for testing.

    Returns:
        InMemoryVaultClient with empty state
    """
    from app.services.vault_clients import InMemoryVaultClient

    return InMemoryVaultClient()


@pytest.fixture
def vault_service(in_memory_vault):
    """Create a vault service with in-memory backend.

    Args:
        in_memory_vault: The in-memory vault client

    Returns:
        VaultService wrapping the in-memory client
    """
    from app.services.vault_service import VaultService

    return VaultService(in_memory_vault, "secret")


@pytest.fixture
def did_service(db_connector, vault_service):
    """Create a DIDService for testing.

    Note: Does NOT use the singleton pattern - creates a fresh instance
    with injected dependencies for test isolation.

    Pre-populates vault with signing keys for test divisions.

    Args:
        db_connector: MongoConnector instance
        vault_service: VaultService instance

    Returns:
        DIDService instance with test dependencies
    """
    from app.services.did_service import DIDService

    # Pre-populate vault with test signing keys
    vault_service.ensure_division_signing_key("epdw")
    vault_service.ensure_division_signing_key("advisory")

    # Create fresh instance with DI (bypasses singleton)
    return DIDService(
        db=db_connector,
        vault_svc=vault_service,
        run_migrations=True,
        ensure_signing_keys=False,  # Already done above
    )


@pytest.fixture
def did_service_no_migrations(db_connector, vault_service):
    """Create a DIDService without running migrations (for mongomock compatibility).

    Mongomock doesn't support validator parameters in create_collection,
    so we manually create the collections and indexes instead.

    Use this fixture for unit tests that need to run with mongomock.

    Args:
        db_connector: MongoConnector instance
        vault_service: VaultService instance

    Returns:
        DIDService instance with manually created collections
    """
    from app.services.did_service import DIDService

    # Manually create the did_artefacts collection with indexes
    artefacts_collection = db_connector.get_collection("did_artefacts")
    artefacts_collection.create_index([("version_uid", 1)], unique=True, name="idx_version_uid")
    artefacts_collection.create_index(
        [("external_uid", 1), ("version", 1)],
        unique=True,
        name="idx_external_uid_version"
    )
    artefacts_collection.create_index([("provenance", 1)], name="idx_provenance")

    # Manually create the did_issued_vcs collection with indexes
    vcs_collection = db_connector.get_collection("did_issued_vcs")
    vcs_collection.create_index([("vc_uid", 1)], unique=True, name="idx_vc_uid")
    vcs_collection.create_index([("version_uid", 1)], unique=True, name="idx_version_uid")

    # Create DIDService without running migrations
    return DIDService(
        db=db_connector,
        vault_svc=vault_service,
        run_migrations=False,
        ensure_signing_keys=False,  # Already done above
    )


@pytest.fixture
def sut_service(db_connector, did_service):
    """Create a SUTService for testing.

    Args:
        db_connector: MongoConnector instance
        did_service: DIDService instance

    Returns:
        SUTService instance with test dependencies
    """
    from app.services.sut_service import SUTService

    return SUTService(db=db_connector, did_svc=did_service)


# =============================================================================
# Shared Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_uuid() -> str:
    """A valid UUID string for testing."""
    return "12345678-1234-1234-1234-123456789abc"


@pytest.fixture
def sample_uuid_2() -> str:
    """Another valid UUID string for testing."""
    return "87654321-4321-4321-4321-cba987654321"


@pytest.fixture
def sample_version_uid() -> str:
    """A valid version UUID string for testing."""
    return "abcdef12-abcd-abcd-abcd-abcdef123456"


@pytest.fixture
def sample_multihash() -> str:
    """A valid SHA-256 multihash for testing."""
    return "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"


@pytest.fixture
def sample_secret_key_hex() -> str:
    """A valid 32-byte Ed25519 seed as hex string.

    This is a test key - DO NOT use in production.
    """
    return "a" * 64  # 32 bytes as hex (64 hex chars)


@pytest.fixture
def signing_key(sample_secret_key_hex):
    """An Ed25519 SigningKey for testing."""
    from app.did_utils.eddsa import create_keypair_from_hex

    return create_keypair_from_hex(sample_secret_key_hex)


@pytest.fixture
def sample_vc() -> dict:
    """A minimal valid VC for testing."""
    return {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
            "https://did.amd.com/contexts/digitalArtefacts/v1",
        ],
        "type": ["VerifiableCredential", "DigitalArtefactCredential"],
        "issuer": "did:web:did.amd.com:epdw",
        "issuanceDate": "2024-01-01T00:00:00+00:00",
        "credentialSubject": {
            "id": "did:web:did.amd.com:12345678-1234-1234-1234-123456789abc",
            "version": 1,
            "versionUid": "did:web:did.amd.com:abcdef12-abcd-abcd-abcd-abcdef123456",
            "creationDate": "2024-01-01T00:00:00+00:00",
        }
    }


@pytest.fixture
def sample_vc_with_proof(sample_vc) -> dict:
    """A VC with a proof for testing removal."""
    vc = sample_vc.copy()
    vc["proof"] = {
        "type": "DataIntegrityProof",
        "cryptosuite": "eddsa-rdfc-2022",
        "created": "2024-01-01T00:00:00+00:00",
        "verificationMethod": "did:web:did.amd.com:epdw#key-1",
        "proofPurpose": "assertionMethod",
        "proofValue": "z58DAdFfa9SkqZMVPxAQpic7ndTeel..."
    }
    return vc


@pytest.fixture
def sample_vp(sample_vc_with_proof) -> dict:
    """A minimal VP with embedded VC for testing."""
    return {
        "@context": [
            "https://www.w3.org/2018/credentials/v1",
        ],
        "type": ["VerifiablePresentation"],
        "holder": "did:web:did.amd.com:holder123",
        "verifiableCredential": [sample_vc_with_proof],
    }
