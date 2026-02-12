# db_connector.py
from typing import Callable
from dataclasses import dataclass
from uuid import UUID, uuid4
from pymongo import MongoClient
from pymongo.synchronous import database
import logging, sys, time, re
from datetime import datetime, timezone

from app.services.vault import (
    vault_fetch_secret
)

# -----------------------------------------------------------
# Logging
# -----------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("db_connector")

# ===========================================================
# Vault KV v2 Reader (ONLY)
# ===========================================================

class _MongoDBConfig:
    """Config parameters for MongoDB connection."""
    conn_string : str
    db_name : str
    def __init__(self, conn_str : str, db_name : str):
        self.conn_string = conn_str
        self.db_name = db_name


def _vault_read_mongo() -> _MongoDBConfig:
    """
    Reads KV v2 secret stored at: secret/data/mongo
    Your Vault path is:
        secret → mount
        mongo  → key
    """
    try:
        logger.info("Reading Mongo config from Vault KV v2 → secret/data/mongo")
        data = vault_fetch_secret("mongo")
        if not data:
            raise RuntimeError("Vault secret 'mongo' is empty.")

        cfg = _MongoDBConfig(data["connection_string"], data["database_name"])

        if not cfg.conn_string:
            raise RuntimeError("Vault missing key: connection_string")

        if not cfg.db_name:
            raise RuntimeError("Vault missing key: database_name")

        return cfg

    except Exception as e:
        raise RuntimeError(
            f"Failed to read Vault KV v2 secret at secret/data/mongo → {e}"
        )

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
class MongoConnector:
    """MongoDB connector using Vault KV v2 secrets only."""

    db : database.Database

    def __init__(self):
        cfg = _vault_read_mongo()

        logger.info(f"Mongo target DB: {cfg.db_name}")
        logger.info(f"Connecting to MongoDB at {cfg.conn_string}")

        self.client = None

        use_tls = (
            cfg.conn_string.startswith("mongodb+srv://")
            or "mongodb.net" in cfg.conn_string
        )

        # Retry logic
        for attempt in range(3):
            try:
                self.client = MongoClient(
                    cfg.conn_string,
                    tls=use_tls,
                    tlsAllowInvalidCertificates=True,
                    tlsAllowInvalidHostnames=True,
                    serverSelectionTimeoutMS=10000,
                    connectTimeoutMS=10000,
                )
                # Force connection test
                self.client.admin.command("ping")

                self.db = self.client[cfg.db_name]
                logger.info(f"✅ Connected to MongoDB: {cfg.db_name}")
                break
            except Exception as e:
                logger.error(f"[Attempt {attempt+1}/3] Mongo connection failed → {e}")
                time.sleep(3)

        if self.db is None:
            raise RuntimeError("❌ Could not connect to MongoDB after 3 attempts.")

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


_db : MongoConnector | None = None
def get_global_db() -> MongoConnector:
    """Return global DB connector."""
    global _db
    if _db is None:
        _db = MongoConnector()
    return _db
