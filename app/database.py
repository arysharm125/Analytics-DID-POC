# db_connector.py
from pymongo import MongoClient
import logging, sys, time
from datetime import datetime

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


# ===========================================================
# MongoConnector Class
# ===========================================================

class MongoConnector:
    """MongoDB connector using Vault KV v2 secrets only."""

    def __init__(self):
        cfg = _vault_read_mongo()

        logger.info(f"Mongo target DB: {cfg.db_name}")
        logger.info(f"Connecting to MongoDB at {cfg.conn_string}")

        self.client = None
        self.db = None

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

