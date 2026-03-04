"""Shared fixtures and configuration for VC compatibility tests."""

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def module_in_memory_vault():
    """Create a module-scoped in-memory vault for VC compatibility tests.

    This ensures all tests in the module use the same vault instance,
    so signing keys remain consistent across VCs and DID documents.
    """
    from app.services.vault_clients import InMemoryVaultClient
    return InMemoryVaultClient()


@pytest.fixture(scope="module")
def module_vault_service(module_in_memory_vault):
    """Create a module-scoped vault service for VC compatibility tests.

    Args:
        module_in_memory_vault: The module-scoped in-memory vault client

    Returns:
        VaultService wrapping the module-scoped vault client
    """
    from app.services.vault_service import VaultService
    return VaultService(module_in_memory_vault, "secret")


@pytest.fixture(scope="module")
def module_db_connector():
    """Create a module-scoped database connector for VC compatibility tests.

    Uses mongomock for fast, isolated testing.

    Returns:
        MongoConnector instance with module-scoped database
    """
    import mongomock

    from app.database import MongoConnector

    client = mongomock.MongoClient()
    db_name = "vc_compat_test"
    return MongoConnector.from_client(client, db_name)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Path to the VC compatibility fixtures directory.

    Returns:
        Path object pointing to tests/fixtures/vc_compat/
    """
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "vc_compat"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    return fixtures_dir


@pytest.fixture(scope="session")
def vcs_dir(fixtures_dir: Path) -> Path:
    """Path to the VCs subdirectory within fixtures.

    Returns:
        Path object pointing to tests/fixtures/vc_compat/vcs/
    """
    vcs_dir = fixtures_dir / "vcs"
    vcs_dir.mkdir(parents=True, exist_ok=True)
    return vcs_dir


@pytest.fixture(scope="module")
def did_service_no_migrations_with_keys(module_db_connector, module_vault_service):
    """Create a DIDService without migrations but with signing keys pre-populated.

    This fixture is module-scoped to ensure all tests in the module use the same
    vault keys, so VCs and DID documents are consistent.

    Args:
        module_db_connector: Module-scoped MongoConnector instance
        module_vault_service: Module-scoped VaultService instance

    Returns:
        DIDService instance with manually created collections and signing keys
    """
    from app.services.did_service import DIDService

    # Pre-populate vault with signing keys for all divisions
    module_vault_service.ensure_division_signing_key("epdw")
    module_vault_service.ensure_division_signing_key("advisory")

    # Create collections with indexes (single source of truth in DIDService)
    DIDService.ensure_collections_for_testing(module_db_connector)

    # Create DIDService without running migrations
    return DIDService(
        db=module_db_connector,
        vault_svc=module_vault_service,
        run_migrations=False,
        ensure_signing_keys=False,  # Already done above
    )
