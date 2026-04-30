"""Integration tests for app/database.py migration mechanism.

These tests verify the migration system works correctly with real MongoDB,
including collection creation, validators, indexes, and execution ordering.

Run with: pytest tests/integration/test_database_migrations.py --db-mode=container
"""

from datetime import datetime, timezone

import pytest
from pymongo.errors import WriteError

from app.database import MigrationName, MigrationSet, MongoConnector


@pytest.mark.integration
class TestMigrationExecution:
    """Test basic migration execution and ordering."""

    def test_run_migrations_executes_pending_migrations(self, db_connector):
        """New migrations should be executed in order and recorded."""
        # Track execution order
        execution_log = []

        # Create test migration set
        migrations = MigrationSet("test")

        @migrations.migration
        def migration_20260101001_first(db: MongoConnector) -> None:
            execution_log.append("first")
            db.get_collection("test_first").insert_one({"executed": True})

        @migrations.migration
        def migration_20260102002_second(db: MongoConnector) -> None:
            execution_log.append("second")
            db.get_collection("test_second").insert_one({"executed": True})

        # Run migrations
        db_connector.run_migrations(migrations)

        # Verify both were executed
        assert execution_log == ["first", "second"]

        # Verify side effects
        assert db_connector.get_collection("test_first").find_one({"executed": True})
        assert db_connector.get_collection("test_second").find_one({"executed": True})

        # Verify both were recorded
        migrations_col = db_connector.get_collection("did_service_migrations")
        recorded = list(migrations_col.find({}, {"name": 1, "_id": 0}))
        recorded_names = sorted([r["name"] for r in recorded])

        assert "20260101001_test_first" in recorded_names
        assert "20260102002_test_second" in recorded_names

    def test_run_migrations_skips_already_applied(self, db_connector):
        """Running migrations twice should not re-execute them."""
        execution_count = {"count": 0}

        migrations = MigrationSet("test")

        @migrations.migration
        def migration_20260101001_counting(db: MongoConnector) -> None:
            execution_count["count"] += 1

        # Run migrations first time
        db_connector.run_migrations(migrations)
        assert execution_count["count"] == 1

        # Run migrations second time
        db_connector.run_migrations(migrations)
        assert execution_count["count"] == 1  # Should NOT increment

    def test_run_migrations_executes_in_sorted_order(self, db_connector):
        """Migrations should execute in date_slug order, not registration order."""
        execution_log = []

        migrations = MigrationSet("test")

        # Register in intentionally wrong order
        @migrations.migration
        def migration_20260301003_third(db: MongoConnector) -> None:
            execution_log.append("third")

        @migrations.migration
        def migration_20260101001_first(db: MongoConnector) -> None:
            execution_log.append("first")

        @migrations.migration
        def migration_20260201002_second(db: MongoConnector) -> None:
            execution_log.append("second")

        # Run migrations
        db_connector.run_migrations(migrations)

        # Verify execution order was sorted by date_slug
        assert execution_log == ["first", "second", "third"]

    def test_run_migrations_only_runs_new_migrations(self, db_connector):
        """If some migrations already applied, only new ones should run."""
        execution_log = []

        migrations = MigrationSet("test")

        @migrations.migration
        def migration_20260101001_already_done(db: MongoConnector) -> None:
            execution_log.append("already_done")

        @migrations.migration
        def migration_20260102002_pending(db: MongoConnector) -> None:
            execution_log.append("pending")

        @migrations.migration
        def migration_20260103003_also_pending(db: MongoConnector) -> None:
            execution_log.append("also_pending")

        # Manually record first migration as applied
        migrations_col = db_connector.get_collection("did_service_migrations")
        migrations_col.insert_one({
            "name": "20260101001_test_already_done",
            "applied_at": datetime.now(timezone.utc),
        })

        # Run migrations
        db_connector.run_migrations(migrations)

        # Only new migrations should have executed
        assert execution_log == ["pending", "also_pending"]


@pytest.mark.integration
class TestMigrationFailureHandling:
    """Test migration error handling and atomicity."""

    def test_run_migrations_stops_on_failure(self, db_connector):
        """If a migration fails, subsequent migrations should not run."""
        execution_log = []

        migrations = MigrationSet("test")

        @migrations.migration
        def migration_20260101001_succeeds(db: MongoConnector) -> None:
            execution_log.append("succeeds")

        @migrations.migration
        def migration_20260102002_fails(db: MongoConnector) -> None:
            execution_log.append("fails")
            raise ValueError("Intentional failure")

        @migrations.migration
        def migration_20260103003_never_runs(db: MongoConnector) -> None:
            execution_log.append("never_runs")

        # Run migrations, expect RuntimeError
        with pytest.raises(RuntimeError, match=r"Migration.*failed"):
            db_connector.run_migrations(migrations)

        # Verify only first migration executed
        assert execution_log == ["succeeds", "fails"]

        # Verify only successful migration was recorded
        migrations_col = db_connector.get_collection("did_service_migrations")
        recorded = list(migrations_col.find({}, {"name": 1, "_id": 0}))
        recorded_names = [r["name"] for r in recorded]

        assert "20260101001_test_succeeds" in recorded_names
        assert "20260102002_test_fails" not in recorded_names
        assert "20260103003_test_never_runs" not in recorded_names

    def test_failed_migration_not_recorded(self, db_connector):
        """A migration that raises should not be recorded as applied."""
        migrations = MigrationSet("test")

        @migrations.migration
        def migration_20260101001_fails(db: MongoConnector) -> None:
            raise RuntimeError("This migration fails")

        # Run migrations, expect failure
        with pytest.raises(RuntimeError):
            db_connector.run_migrations(migrations)

        # Verify migration was NOT recorded
        migrations_col = db_connector.get_collection("did_service_migrations")
        recorded = migrations_col.find_one({"name": "20260101001_test_fails"})
        assert recorded is None


@pytest.mark.integration
class TestMigrationCollection:
    """Test migration collection initialization and metadata."""

    def test_ensures_migrations_collection_created(self, db_connector):
        """First run_migrations call should create the _migrations collection."""
        # Verify collection doesn't exist initially
        collections_before = db_connector.db.list_collection_names()
        assert "did_service_migrations" not in collections_before

        # Run migrations (even empty set)
        empty_migrations = MigrationSet("test")
        db_connector.run_migrations(empty_migrations)

        # Verify collection now exists
        collections_after = db_connector.db.list_collection_names()
        assert "did_service_migrations" in collections_after

        # Verify it has the expected unique index on 'name'
        migrations_col = db_connector.get_collection("did_service_migrations")
        indexes = migrations_col.index_information()
        assert "name_1" in indexes
        assert indexes["name_1"]["unique"] is True

    def test_migration_records_applied_at_timestamp(self, db_connector):
        """Recorded migrations should have accurate applied_at timestamps."""
        before_time = datetime.now(timezone.utc)

        migrations = MigrationSet("test")

        @migrations.migration
        def migration_20260101001_timestamped(db: MongoConnector) -> None:
            pass

        db_connector.run_migrations(migrations)

        after_time = datetime.now(timezone.utc)

        # Check timestamp
        migrations_col = db_connector.get_collection("did_service_migrations")
        record = migrations_col.find_one({"name": "20260101001_test_timestamped"})

        assert record is not None
        assert "applied_at" in record
        applied_at = record["applied_at"]

        # Verify timestamp is between before and after
        assert before_time <= applied_at <= after_time

    def test_ensure_collection_idempotent(self, db_connector):
        """Calling run_migrations multiple times should not fail on collection creation."""
        migrations = MigrationSet("test")

        @migrations.migration
        def migration_20260101001_test(db: MongoConnector) -> None:
            pass

        # First run creates collection
        db_connector.run_migrations(migrations)

        # Second run should not error on collection already existing
        db_connector.run_migrations(migrations)

        # Collection should still exist and work
        migrations_col = db_connector.get_collection("did_service_migrations")
        assert migrations_col.count_documents({}) == 1


@pytest.mark.integration
class TestMultiModuleMigrations:
    """Test migration isolation between different modules."""

    def test_different_modules_tracked_separately(self, db_connector):
        """Migrations from different modules should have distinct full_names."""
        # Create two migration sets with same migration names
        migrations_a = MigrationSet("moduleA")
        migrations_b = MigrationSet("moduleB")

        @migrations_a.migration
        def migration_20260101001_init(db: MongoConnector) -> None:
            db.get_collection("test_module_a").insert_one({"module": "A"})

        @migrations_b.migration
        def _migration_20260101001_init(db: MongoConnector) -> None:
            db.get_collection("test_module_b").insert_one({"module": "B"})

        # Run both migration sets
        db_connector.run_migrations(migrations_a)
        db_connector.run_migrations(migrations_b)

        # Verify both were recorded with different full names
        migrations_col = db_connector.get_collection("did_service_migrations")
        recorded = list(migrations_col.find({}, {"name": 1, "_id": 0}))
        recorded_names = sorted([r["name"] for r in recorded])

        assert "20260101001_moduleA_init" in recorded_names
        assert "20260101001_moduleB_init" in recorded_names

        # Verify both executed
        assert db_connector.get_collection("test_module_a").find_one({"module": "A"})
        assert db_connector.get_collection("test_module_b").find_one({"module": "B"})

    def test_migration_full_name_format(self, db_connector):
        """Recorded migration names should follow format: date_module_title."""
        migrations = MigrationSet("did")

        @migrations.migration
        def migration_20260212001_add_index(db: MongoConnector) -> None:
            pass

        db_connector.run_migrations(migrations)

        # Verify recorded name format
        migrations_col = db_connector.get_collection("did_service_migrations")
        record = migrations_col.find_one({})

        assert record["name"] == "20260212001_did_add_index"


@pytest.mark.integration
class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_run_migrations_with_empty_set(self, db_connector):
        """Running empty migration set should complete without error."""
        empty_migrations = MigrationSet("empty")

        # Should not raise
        db_connector.run_migrations(empty_migrations)

        # Migration collection should still be created
        assert "did_service_migrations" in db_connector.db.list_collection_names()


@pytest.mark.integration
class TestSchemaEvolution:
    """Test patterns from did_service.py: schema evolution with collMod."""

    def test_schema_evolution_sequential_migrations(self, db_connector):
        """Sequential migrations that modify schemas should build correctly."""
        migrations = MigrationSet("schema")

        @migrations.migration
        def migration_20260101001_create_collection(db: MongoConnector) -> None:
            """Create collection with initial validator."""
            validator = {
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": ["field1"],
                    "properties": {
                        "field1": {"bsonType": "string"},
                    }
                }
            }
            db.db.create_collection("test_schema", validator=validator)

        @migrations.migration
        def migration_20260102002_add_field(db: MongoConnector) -> None:
            """Add field2 to validator using collMod."""
            validator = {
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": ["field1"],
                    "properties": {
                        "field1": {"bsonType": "string"},
                        "field2": {"bsonType": "int"},
                    }
                }
            }
            db.db.command({
                "collMod": "test_schema",
                "validator": validator,
            })

        @migrations.migration
        def migration_20260103003_add_index(db: MongoConnector) -> None:
            """Add an index."""
            collection = db.get_collection("test_schema")
            collection.create_index([("field1", 1)], name="idx_field1")

        # Run all migrations
        db_connector.run_migrations(migrations)

        # Verify collection exists
        assert "test_schema" in db_connector.db.list_collection_names()

        # Verify final validator includes both fields
        collection_info = db_connector.db.command("listCollections", filter={"name": "test_schema"})
        collection_doc = collection_info["cursor"]["firstBatch"][0]
        validator = collection_doc["options"]["validator"]

        assert "field1" in validator["$jsonSchema"]["properties"]
        assert "field2" in validator["$jsonSchema"]["properties"]

        # Verify index exists
        collection = db_connector.get_collection("test_schema")
        indexes = collection.index_information()
        assert "idx_field1" in indexes

    def test_collmod_migration_updates_validator(self, db_connector):
        """Migrations using collMod should successfully update validators."""
        migrations = MigrationSet("collmod")

        @migrations.migration
        def migration_20260101001_create(db: MongoConnector) -> None:
            validator = {
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": ["original"],
                    "properties": {
                        "original": {"bsonType": "string"},
                    }
                }
            }
            db.db.create_collection("test_collmod", validator=validator)

        @migrations.migration
        def migration_20260102002_modify(db: MongoConnector) -> None:
            validator = {
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": ["original", "new"],
                    "properties": {
                        "original": {"bsonType": "string"},
                        "new": {"bsonType": "int"},
                    }
                }
            }
            db.db.command({
                "collMod": "test_collmod",
                "validator": validator,
            })

        db_connector.run_migrations(migrations)

        # Try inserting valid document
        collection = db_connector.get_collection("test_collmod")
        collection.insert_one({"original": "test", "new": 42})

        # Try inserting invalid document (missing new field)
        with pytest.raises(WriteError):
            collection.insert_one({"original": "test"})

    def test_migration_dependency_failure(self, db_connector):
        """Migration that modifies non-existent collection should fail."""
        migrations = MigrationSet("broken")

        @migrations.migration
        def migration_20260101001_modifies_nonexistent(db: MongoConnector) -> None:
            """Try to modify a collection that doesn't exist."""
            db.db.command({
                "collMod": "does_not_exist",
                "validator": {"$jsonSchema": {"bsonType": "object"}},
            })

        # Should fail
        with pytest.raises(RuntimeError):
            db_connector.run_migrations(migrations)

    def test_indexes_created_by_migrations(self, db_connector):
        """Migrations should create expected indexes."""
        migrations = MigrationSet("indexes")

        @migrations.migration
        def migration_20260101001_create_indexes(db: MongoConnector) -> None:
            collection = db.get_collection("test_indexes")

            # Create various indexes
            collection.create_index([("field1", 1)], unique=True, name="idx_field1_unique")
            collection.create_index([("field2", 1), ("field3", -1)], name="idx_field2_field3")
            collection.create_index([("tags", 1)], name="idx_tags")

        db_connector.run_migrations(migrations)

        # Verify indexes exist
        collection = db_connector.get_collection("test_indexes")
        indexes = collection.index_information()

        assert "idx_field1_unique" in indexes
        assert indexes["idx_field1_unique"]["unique"] is True

        assert "idx_field2_field3" in indexes
        assert indexes["idx_field2_field3"]["key"] == [("field2", 1), ("field3", -1)]

        assert "idx_tags" in indexes

    def test_validator_rejects_invalid_documents(self, db_connector):
        """Documents violating validator should be rejected after migrations run."""
        migrations = MigrationSet("validation")

        @migrations.migration
        def migration_20260101001_strict_validator(db: MongoConnector) -> None:
            validator = {
                "$jsonSchema": {
                    "bsonType": "object",
                    "required": ["required_field"],
                    "properties": {
                        "required_field": {
                            "bsonType": "string",
                            "pattern": "^[A-Z]+$",  # Only uppercase letters
                        }
                    }
                }
            }
            db.db.create_collection(
                "test_validation",
                validator=validator,
                validationLevel="strict",
                validationAction="error"
            )

        db_connector.run_migrations(migrations)

        collection = db_connector.get_collection("test_validation")

        # Valid document should work
        collection.insert_one({"required_field": "VALID"})

        # Invalid document (missing field) should fail
        with pytest.raises(WriteError):
            collection.insert_one({"other_field": "value"})

        # Invalid document (wrong pattern) should fail
        with pytest.raises(WriteError):
            collection.insert_one({"required_field": "invalid123"})


@pytest.mark.integration
class TestMigrationNameValidation:
    """Test MigrationName validation rules."""

    def test_migration_name_valid_formats(self):
        """Valid migration names should be accepted."""
        # Valid date_slug and title
        name = MigrationName("20260212001", "add_index")
        assert str(name) == "20260212001_add_index"

        # Title with hyphens
        name = MigrationName("20260212001", "add-user-index")
        assert str(name) == "20260212001_add-user-index"

        # Title with mixed case
        name = MigrationName("20260212001", "AddIndex")
        assert str(name) == "20260212001_AddIndex"

    def test_migration_name_invalid_date_slug(self):
        """Invalid date_slug formats should be rejected."""
        # Too short
        with pytest.raises(ValueError, match="date_slug must be YYYYMMDDCCC"):
            MigrationName("2026021200", "title")

        # Too long
        with pytest.raises(ValueError, match="date_slug must be YYYYMMDDCCC"):
            MigrationName("202602120001", "title")

        # Non-numeric
        with pytest.raises(ValueError, match="date_slug must be YYYYMMDDCCC"):
            MigrationName("2026021200A", "title")

    def test_migration_name_invalid_title(self):
        """Invalid title formats should be rejected."""
        # Special characters
        with pytest.raises(ValueError, match="title must contain only"):
            MigrationName("20260212001", "add@index")

        # Spaces
        with pytest.raises(ValueError, match="title must contain only"):
            MigrationName("20260212001", "add index")

        # Empty
        with pytest.raises(ValueError, match="title must contain only"):
            MigrationName("20260212001", "")


@pytest.mark.integration
class TestConnectionPoolStats:
    """Test connection pool statistics with real MongoDB."""

    def test_get_pool_stats_with_real_mongodb(self, db_connector):
        """get_pool_stats should return ConnectionPoolStats or None with real MongoDB."""
        from app.database import ConnectionPoolStats

        result = db_connector.get_pool_stats()

        # With real MongoDB, may return stats or None depending on PyMongo internals
        if result is not None:
            assert isinstance(result, ConnectionPoolStats)
            assert result.max_pool_size > 0
            assert result.min_pool_size >= 0
            assert result.current_size >= 0
            assert result.available_count >= 0
            assert result.in_use_count >= 0
            assert result.wait_queue_size >= 0
            assert result.pool_health in ("healthy", "warning", "critical")

            # Verify pool configuration values match expected range
            assert result.max_pool_size <= 1000  # Reasonable upper bound
            assert result.min_pool_size < result.max_pool_size


@pytest.mark.integration
class TestMigrationSetValidation:
    """Test MigrationSet validation and decorator."""

    def test_migration_set_valid_module_names(self):
        """Valid module names should be accepted."""
        # Simple name
        ms = MigrationSet("did")
        assert ms.module == "did"

        # Mixed case
        ms = MigrationSet("DIDService")
        assert ms.module == "DIDService"

        # Numbers
        ms = MigrationSet("module123")
        assert ms.module == "module123"

    def test_migration_set_invalid_module_names(self):
        """Invalid module names should be rejected."""
        # Underscores
        with pytest.raises(ValueError, match="module must be a single ASCII word"):
            MigrationSet("module_name")

        # Hyphens
        with pytest.raises(ValueError, match="module must be a single ASCII word"):
            MigrationSet("module-name")

        # Spaces
        with pytest.raises(ValueError, match="module must be a single ASCII word"):
            MigrationSet("module name")

        # Special characters
        with pytest.raises(ValueError, match="module must be a single ASCII word"):
            MigrationSet("module@name")

    def test_migration_decorator_validates_function_name(self):
        """Migration decorator should validate function name format."""
        migrations = MigrationSet("test")

        # Valid format
        @migrations.migration
        def migration_20260212001_valid_name(db: MongoConnector) -> None:
            pass

        # Valid with underscore prefix
        @migrations.migration
        def _migration_20260212002_also_valid(db: MongoConnector) -> None:
            pass

        # Invalid: wrong prefix
        with pytest.raises(ValueError, match="must match pattern"):
            @migrations.migration
            def migation_20260212001_typo(db: MongoConnector) -> None:
                pass

        # Invalid: wrong date format
        with pytest.raises(ValueError, match="must match pattern"):
            @migrations.migration
            def migration_2026021_wrong_date(db: MongoConnector) -> None:
                pass
