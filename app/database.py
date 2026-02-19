# db_connector.py
"""MongoDB connector with factory methods for different initialization strategies.

This module provides MongoConnector for database access. Use factory methods
to create instances:

- MongoConnector.from_uri(): Connect with explicit connection string
- MongoConnector.from_client(): Use existing MongoClient (e.g., mongomock)
- MongoConnector.from_vault_service(): Read config from VaultService (production)

For FastAPI applications, use the get_db() dependency from app.routers.dependencies.
"""
from __future__ import annotations
from typing import Callable, TYPE_CHECKING
from dataclasses import dataclass
from uuid import UUID, uuid4
from pymongo import MongoClient
from pymongo.synchronous import database
import logging
import sys
import time
import re
from datetime import datetime, timezone

if TYPE_CHECKING:
    from app.services.vault_service import VaultService

# -----------------------------------------------------------
# Logging
# -----------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("db_connector")

# Type alias for migration functions
MigrationFunc = Callable[["MongoConnector"], None]

# Validation patterns for MigrationName
_RE_DATE_SLUG = re.compile(r"^\d{8}\d{3}$")
_RE_TITLE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class MigrationName:
    """Migration identifier with validated components.

    Args:
        date_slug: YYYYMMDDCCC format (8 date digits + 3-digit counter, e.g. "20250212001")
        title: ASCII word chars plus _ and - [A-Za-z0-9_-]+ (e.g. "add_index")
    """
    date_slug: str
    title: str

    def __post_init__(self) -> None:
        if not _RE_DATE_SLUG.match(self.date_slug):
            raise ValueError(
                f"date_slug must be YYYYMMDDCCC (11 digits), got: {self.date_slug!r}"
            )
        if not _RE_TITLE.match(self.title):
            raise ValueError(
                f"title must contain only [A-Za-z0-9_-], got: {self.title!r}"
            )

    def __str__(self) -> str:
        return f"{self.date_slug}_{self.title}"


# Pattern to extract date_slug and title from function name
# Matches: migration_YYYYMMDDCCC_title or _migration_YYYYMMDDCCC_title
_RE_MIGRATION_FUNC_NAME = re.compile(r"^_?migration_(\d{11})_([A-Za-z0-9_-]+)$")


class MigrationSet:
    """A set of migrations belonging to a specific module.

    Args:
        module: Module identifier (ASCII alphanumeric, e.g. "did", "audit")
        migrations: Dict mapping MigrationName to migration functions

    Example using decorator:
        migrations = MigrationSet("did")

        @migrations.migration
        def migration_20260212001_init(db: MongoConnector) -> None:
            pass
    """
    _RE_MODULE = re.compile(r"^[A-Za-z0-9]+$")

    def __init__(self, module: str, migrations: dict[MigrationName, MigrationFunc] | None = None):
        if not self._RE_MODULE.match(module):
            raise ValueError(
                f"module must be a single ASCII word [A-Za-z0-9]+, got: {module!r}"
            )
        self._module = module
        self._migrations: dict[MigrationName, MigrationFunc] = migrations or {}

    @property
    def module(self) -> str:
        return self._module

    @property
    def migrations(self) -> dict[MigrationName, MigrationFunc]:
        return self._migrations

    def add(self, name: MigrationName, func: MigrationFunc) -> None:
        """Add a migration to the set."""
        self._migrations[name] = func

    def migration(self, func: MigrationFunc) -> MigrationFunc:
        """Decorator to register a migration function.

        The function name must follow the pattern: migration_YYYYMMDDCCC_title
        (optionally prefixed with underscore: _migration_YYYYMMDDCCC_title)

        Example:
            @migrations.migration
            def migration_20260212001_add_index(db: MongoConnector) -> None:
                db.get_collection("items").create_index([("field", 1)])
        """
        match = _RE_MIGRATION_FUNC_NAME.match(func.__name__)
        if not match:
            raise ValueError(
                f"Migration function name must match pattern "
                f"'migration_YYYYMMDDCCC_title', got: {func.__name__!r}"
            )
        date_slug, title = match.groups()
        name = MigrationName(date_slug, title)
        self._migrations[name] = func
        return func

    def full_name(self, name: MigrationName) -> str:
        """Get the full migration name including module."""
        return f"{name.date_slug}_{self._module}_{name.title}"

    def keys(self):
        return self._migrations.keys()

    def __getitem__(self, key: MigrationName) -> MigrationFunc:
        return self._migrations[key]

    def __len__(self) -> int:
        return len(self._migrations)

# ===========================================================
# MongoConnector Class
# ===========================================================

_MIGRATIONS_COLLECTION = "did_service_migrations"


class MongoConnectorInitError(Exception):
    """Raised when MongoConnector() is called directly."""
    pass


class MongoConnector:
    """MongoDB connector with factory methods for initialization.

    Use factory methods to create instances:

    - from_uri(): Connect to a specific MongoDB using connection string
    - from_client(): Use an existing MongoClient (for mongomock testing)
    - from_vault_service(): Read config from VaultService (production)

    For FastAPI applications, use the get_db() dependency from
    app.routers.dependencies which handles initialization automatically.

    Example usage:
        # Production with dependency injection
        from app.routers.dependencies import get_db
        vault_svc = get_vault()
        db = MongoConnector.from_vault_service(vault_svc)

        # Testing with mongomock
        import mongomock
        client = mongomock.MongoClient()
        db = MongoConnector.from_client(client, "test_db")

        # Testing with real MongoDB
        db = MongoConnector.from_uri("mongodb://localhost:27017", "test_db")
    """

    db: database.Database
    client: MongoClient | None

    def __init__(self):
        """Direct instantiation is not supported.

        Use factory methods instead:
        - MongoConnector.from_uri(conn_string, db_name)
        - MongoConnector.from_client(client, db_name)
        - MongoConnector.from_vault_service(vault_svc)
        """
        raise MongoConnectorInitError(
            "Direct instantiation of MongoConnector is not supported. "
            "Use factory methods: from_uri(), from_client(), or from_vault_service()"
        )

    def _connect(self, conn_string: str, db_name: str) -> None:
        """Establish connection to MongoDB with retry logic.

        Args:
            conn_string: MongoDB connection string
            db_name: Database name to use

        Raises:
            RuntimeError: If connection fails after 3 attempts
        """
        logger.info(f"Mongo target DB: {db_name}")
        logger.info(f"Connecting to MongoDB...")

        self.client = None

        use_tls = (
            conn_string.startswith("mongodb+srv://")
            or "mongodb.net" in conn_string
        )

        # Retry logic
        for attempt in range(3):
            try:
                self.client = MongoClient(
                    conn_string,
                    tls=use_tls,
                    tlsAllowInvalidCertificates=True,
                    tlsAllowInvalidHostnames=True,
                    serverSelectionTimeoutMS=10000,
                    connectTimeoutMS=10000,
                    tz_aware=True,
                )
                # Force connection test
                self.client.admin.command("ping")

                self.db = self.client[db_name]
                logger.info(f"Connected to MongoDB: {db_name}")
                return
            except Exception as e:
                logger.error(f"[Attempt {attempt+1}/3] Mongo connection failed → {e}")
                time.sleep(3)

        raise RuntimeError("Could not connect to MongoDB after 3 attempts.")

    @classmethod
    def from_uri(cls, conn_string: str, db_name: str) -> "MongoConnector":
        """Create connector from explicit connection URI.

        Use this for testing with a real MongoDB instance or testcontainers.

        Args:
            conn_string: MongoDB connection string
            db_name: Database name

        Returns:
            Configured MongoConnector

        Example:
            # Local MongoDB
            db = MongoConnector.from_uri("mongodb://localhost:27017", "test_db")

            # Testcontainers
            container = MongoDbContainer("mongo:6.0")
            container.start()
            db = MongoConnector.from_uri(container.get_connection_url(), "test_db")
        """
        instance = cls.__new__(cls)
        instance.client = None
        instance._connect(conn_string, db_name)
        return instance

    @classmethod
    def from_client(cls, client: MongoClient, db_name: str) -> "MongoConnector":
        """Create connector from existing MongoClient.

        Use this for testing with mongomock or other mock clients.

        Args:
            client: An existing MongoClient (or mongomock.MongoClient)
            db_name: Database name

        Returns:
            Configured MongoConnector

        Example:
            import mongomock
            client = mongomock.MongoClient()
            db = MongoConnector.from_client(client, "test_db")
        """
        instance = cls.__new__(cls)
        instance.client = client
        instance.db = client[db_name]
        return instance

    @classmethod
    def from_vault_service(cls, vault_svc: VaultService) -> MongoConnector:
        """Create connector by reading config from a VaultService.

        Use this for production with proper dependency injection.

        Args:
            vault_svc: The VaultService instance to read config from

        Returns:
            Configured MongoConnector

        Raises:
            RuntimeError: If vault secret is missing required keys

        Example:
            vault_svc = VaultService(client, mount_point="secret")
            db = MongoConnector.from_vault_service(vault_svc)
        """
        # Import here to avoid circular dependency
        from app.services.vault_service import SecretNotFoundError

        try:
            config = vault_svc.fetch_secret("mongo")
        except SecretNotFoundError as e:
            raise RuntimeError(f"Failed to read MongoDB config from vault: {e}") from e

        conn_string = config.get("connection_string")
        db_name = config.get("database_name")

        if not conn_string:
            raise RuntimeError("Vault secret 'mongo' missing key: connection_string")
        if not db_name:
            raise RuntimeError("Vault secret 'mongo' missing key: database_name")

        return cls.from_uri(conn_string, db_name)

    # -------------------------------------------------------
    def now(self) -> datetime:
        """Return current UTC timestamp for consistent time handling."""
        return datetime.now(timezone.utc)

    def random_uuid(self) -> UUID:
        """Return a random UUIDv4. Use this instead of directly calling uuid4()
        to allow mocking."""
        return uuid4()

    def get_collection(self, name: str):
        if self.db is None:
            raise RuntimeError("MongoConnector not initialized")
        return self.db[name]

    def insert_doc(self, collection_name: str, doc: dict):
        doc["created_at"] = datetime.utcnow()
        return self.get_collection(collection_name).insert_one(doc)

    def update_doc(self, collection_name: str, query: dict, update: dict, upsert=False):
        if "$set" not in update:
            update["$set"] = {}
        update["$set"]["updated_at"] = datetime.utcnow()
        return self.get_collection(collection_name).update_one(query, update, upsert=upsert)

    def fetch_docs(self, collection_name: str, query=None, limit=20):
        return list(self.get_collection(collection_name).find(query or {}).limit(limit))

    def close_connection(self):
        if self.client:
            self.client.close()
            logger.info("MongoDB connection closed")

    # =============================================================================
    # MIGRATION RUNNER
    # =============================================================================

    def _ensure_migrations_collection(self) -> None:
        """Ensure the _migrations collection exists."""
        existing = self.db.list_collection_names()
        if _MIGRATIONS_COLLECTION not in existing:
            self.db.create_collection(_MIGRATIONS_COLLECTION)

            # Create index on migration name for quick lookups
            self.db[_MIGRATIONS_COLLECTION].create_index([("name", 1)], unique=True)
            logger.info(f"Created {_MIGRATIONS_COLLECTION} collection")

    def _get_applied_migrations(self) -> set[str]:
        """Get the set of migration names that have already been applied."""
        migrations_coll = self.db[_MIGRATIONS_COLLECTION]
        cursor = migrations_coll.find({}, {"name": 1})
        applied = set()
        for doc in cursor:
            applied.add(doc["name"])
        return applied

    def _record_migration(self, name: str):
        """Record that a migration has been applied."""
        self.db[_MIGRATIONS_COLLECTION].insert_one({
            "name": name,
            "applied_at": datetime.now(timezone.utc),
        })


    def run_migrations(self, migration_set: MigrationSet):
        """Run any pending migrations from a given migration set.

        Migrations are run in sorted order by name (hence the YYYYMMDD prefix convention).
        Only migrations that haven't been recorded in _migrations are executed.
        The full name (date_module_title) is used for recording and lookup.
        """
        self._ensure_migrations_collection()

        # Filter to migrations not yet applied, then sort by full name
        applied_strs = self._get_applied_migrations()
        pending = sorted(
            [m for m in migration_set.keys() if migration_set.full_name(m) not in applied_strs],
            key=lambda m: migration_set.full_name(m)
        )

        if not pending:
            logger.info(f"No pending migrations for module '{migration_set.module}'")
            return

        logger.info(f"Found {len(pending)} pending migration(s) for module '{migration_set.module}'")

        for migration_name in pending:
            full_name_str = migration_set.full_name(migration_name)
            logger.info(f"Running migration: {full_name_str}")
            try:
                migration_set[migration_name](self)
                self._record_migration(full_name_str)
                logger.info(f"Completed migration: {full_name_str}")
            except Exception as e:
                logger.error(f"Migration {full_name_str} failed: {e}")
                raise RuntimeError(f"Migration {full_name_str} failed") from e
