# db_connector.py
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure, InvalidURI
import os, logging, sys, time
from datetime import datetime
import hvac
import pymongo

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

def _vault_read_mongo():
    """
    Reads KV v2 secret stored at: secret/data/mongo
    Your Vault path is:
        secret → mount
        mongo  → key
    """
    vault_addr = os.getenv("VAULT_ADDR", "http://10.159.22.95:8200")
    vault_token = os.getenv("VAULT_TOKEN")

    if not vault_token:
        raise RuntimeError("VAULT_TOKEN missing — cannot read Vault")

    client = hvac.Client(url=vault_addr, token=vault_token)

    try:
        logger.info("Reading Mongo config from Vault KV v2 → secret/data/mongo")
        secret = client.secrets.kv.v2.read_secret_version(path="mongo")
        data = secret.get("data", {}).get("data", {})
        if not data:
            raise RuntimeError("Vault secret 'mongo' is empty.")
        return data
    except Exception as e:
        raise RuntimeError(
            f"Failed to read Vault KV v2 secret at secret/data/mongo → {e}"
        )

# ===========================================================
# Extract fields
# ===========================================================

def get_mongo_connection_string():
    data = _vault_read_mongo()
    conn = data.get("connection_string")
    if not conn:
        raise RuntimeError("Vault missing key: connection_string")
    return conn

def get_mongo_database_name():
    data = _vault_read_mongo()
    db = data.get("database_name")
    if not db:
        raise RuntimeError("Vault missing key: database_name")
    return db

def get_mongo_collection_name():
    data = _vault_read_mongo()
    coll = data.get("collection_name")
    if not coll:
        raise RuntimeError("Vault missing key: collection_name")
    return coll

# ===========================================================
# MongoConnector Class
# ===========================================================

class MongoConnector:
    """MongoDB connector using Vault KV v2 secrets only."""

    def __init__(self):
        self.uri = get_mongo_connection_string()
        self.db_name = get_mongo_database_name()
        self.collection_name = get_mongo_collection_name()

        logger.info(f"Mongo target DB: {self.db_name}, Collection: {self.collection_name}")
        logger.info(f"Connecting to MongoDB at {self.uri}")

        self.client = None
        self.db = None

        use_tls = (
            self.uri.startswith("mongodb+srv://")
            or "mongodb.net" in self.uri
        )

        # Retry logic
        for attempt in range(3):
            try:
                self.client = pymongo.MongoClient(
                    self.uri,
                    tls=use_tls,
                    tlsAllowInvalidCertificates=True,
                    tlsAllowInvalidHostnames=True,
                    serverSelectionTimeoutMS=10000,
                    connectTimeoutMS=10000,
                )
                # Force connection test
                self.client.admin.command("ping")

                self.db = self.client[self.db_name]
                logger.info(f"✅ Connected to MongoDB: {self.db_name}")
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

