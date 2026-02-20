# Testing Guide

This directory contains the test suite for Analytics-DID-POC backend.

## Quick Start

```bash
# Install development/test dependencies (from project root)
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run only unit tests
pytest tests/unit/

# Run only integration tests
pytest tests/integration/
```

## Test Structure

```
tests/
├── conftest.py           # Shared fixtures and configuration
├── unit/                 # Unit tests (no external dependencies)
│   └── services/         # Service layer unit tests
└── integration/          # Integration tests (require database)
```

## Database Modes

Tests support three database backends:

```bash
# Use mongomock (default, fastest, no setup needed)
pytest --db-mode=mock

# Use real MongoDB in Docker via testcontainers (requires Docker running)
pytest --db-mode=container

# Use existing MongoDB instance
TEST_MONGODB_URI="mongodb://localhost:27017" pytest --db-mode=real
```

**Note:** Integration tests are automatically skipped when using `--db-mode=mock` (the default). Use `--db-mode=container` or `--db-mode=real` to run them.

## Test Markers

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"
```

## Coverage Report

```bash
# Generate coverage report
pytest --cov=app --cov-report=html

# View report
open htmlcov/index.html
```

## Writing Tests

### Unit Tests

Unit tests should not require external services. Use the provided fixtures:

```python
def test_example(in_memory_vault, vault_service):
    """Test with in-memory vault."""
    vault_service.write_secret("test/path", {"key": "value"})
    result = vault_service.fetch_secret("test/path")
    assert result["key"] == "value"
```

### Integration Tests

Integration tests use the `db_connector` fixture for database access:

```python
def test_with_database(db_connector, did_service):
    """Test with isolated database."""
    # Each test gets a fresh database
    artefact = did_service.upsert_artefact(...)
    assert artefact.version == 1
```

### Test Isolation

The `reset_singletons` fixture runs automatically before and after each test to ensure:
- Config cache is cleared
- Vault singletons are reset
- DIDService singleton is reset
- FastAPI dependencies are cleared

This prevents test pollution between test cases.

## Fixtures Reference

| Fixture | Scope | Description |
|---------|-------|-------------|
| `db_connector` | function | MongoConnector with isolated database |
| `in_memory_vault` | function | InMemoryVaultClient for testing |
| `vault_service` | function | VaultService with in-memory backend |
| `did_service` | function | DIDService with test dependencies |
| `sut_service` | function | SUTService with test dependencies |
| `test_config` | function | Test AppConfig |
| `override_test_config` | function | Override app config for test |
