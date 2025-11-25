# db_connector.py
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure, InvalidURI
import os, logging, sys, time
from datetime import datetime
import hvac
import certifi
import pymongo

# -----------------------------------------------------------
# Docker-safe logging setup
# -----------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("db_connector")

# -----------------------------------------------------------
# Vault Secret Fetching
# -----------------------------------------------------------
def get_mongo_uri_from_vault() -> str:
    vault_addr = os.getenv("VAULT_ADDR", "http://10.159.20.87:8200")
    vault_token = os.getenv("VAULT_TOKEN")
    secret_path = "mongo"

    if vault_token:
        try:
            client = hvac.Client(url=vault_addr, token=vault_token)
            if client.is_authenticated():
                secret = client.secrets.kv.v2.read_secret_version(path=secret_path)
                uri = secret.get("data", {}).get("data", {}).get("uri")
                if uri:
                    logger.info("Mongo URI fetched from Vault.")
                    return uri
                logger.warning(f"No 'uri' key found in Vault secret '{secret_path}'.")
        except Exception as e:
            logger.warning(f"Could not fetch Mongo URI from Vault: {e}")
    else:
        logger.warning("VAULT_TOKEN not set — skipping Vault fetch.")

    # Fallback
    MONGO_URI = os.getenv("MONGO_URI")
    DB_NAME = os.getenv("DB_NAME", "benchmark-framework")

    if not MONGO_URI:
        raise RuntimeError("MONGO_URI not found in environment (.env file missing?)")
    
    db_client = MongoConnector(uri=MONGO_URI, db_name=DB_NAME)
    logger.info(f"Using Mongo URI from environment or default: {uri}")
    return uri


def get_db_name_from_vault() -> str:
    vault_addr = os.getenv("VAULT_ADDR", "http://10.159.20.87:8200")
    vault_token = os.getenv("VAULT_TOKEN")
    secret_path = "mongo"

    if vault_token:
        try:
            client = hvac.Client(url=vault_addr, token=vault_token)
            if client.is_authenticated():
                secret = client.secrets.kv.v2.read_secret_version(path=secret_path)
                db_name = secret.get("data", {}).get("data", {}).get("db_name")
                if db_name:
                    logger.info("Database name fetched from Vault.")
                    return db_name
                logger.warning(f"No 'db_name' key found in Vault secret '{secret_path}'.")
        except Exception as e:
            logger.warning(f"Could not fetch DB name from Vault: {e}")
    else:
        logger.warning("VAULT_TOKEN not set — skipping Vault fetch.")

    # Fallback
    db_name = os.getenv("DB_NAME", "benchmark_framework_local")
    logger.info(f"Using DB name from environment or default: {db_name}")
    return db_name

# -----------------------------------------------------------
# MongoConnector Class
# -----------------------------------------------------------
class MongoConnector:
    """Handles connection to MongoDB using credentials fetched from Vault."""
    def __init__(self):
        self.uri = get_mongo_uri_from_vault()
        self.db_name = get_db_name_from_vault()
        self.client = None
        self.db = None

        # Atlas detection — requires TLS
        use_tls = self.uri.startswith("mongodb+srv://") or "mongodb.net" in self.uri

        logger.info(f"Connecting to MongoDB ({'TLS' if use_tls else 'non-TLS'}) at {self.uri}")

        # Retry logic — handles slow DNS / Vault race
        for attempt in range(3):
            try:
                #self.client = MongoClient(
                #    self.uri,
                #    serverSelectionTimeoutMS=10000,
                #    tls=use_tls,
                #    tlsCAFile=certifi.where() if use_tls else None,
                #)
                self.client = pymongo.MongoClient(
                    self.uri,
                    tls=True,
                    tlsAllowInvalidCertificates=True,
                    tlsAllowInvalidHostnames=True,
                    serverSelectionTimeoutMS=10000,
                    connectTimeoutMS=10000,
                )
                self.client.admin.command("ping")
                self.db = self.client[self.db_name]
                logger.info(f"✅ Connected to MongoDB: {self.db_name}")
                break
            except (ConnectionFailure, OperationFailure, InvalidURI) as e:
                logger.error(f"[Attempt {attempt+1}/3] Mongo connection failed: {e}")
                time.sleep(3)
            except Exception as e:
                logger.critical(f"[Attempt {attempt+1}/3] Unexpected Mongo error: {e}")
                time.sleep(3)
        else:
            raise ConnectionFailure(f"❌ Could not connect to MongoDB after 3 attempts. URI={self.uri}")

    # -------------------------------------------------------
    # CRUD helpers
    # -------------------------------------------------------
    def get_collection(self, name: str):
        if self.db is None:
            raise RuntimeError("MongoConnector not initialized.")
        return self.db[name]

    def fetch_docs(self, collection_name: str, query=None, limit=20):
        query = query or {}
        try:
            return list(self.get_collection(collection_name).find(query).limit(limit))
        except Exception as e:
            logger.error(f"Failed to fetch docs: {e}")
            raise

    def insert_doc(self, collection_name: str, doc: dict):
        try:
            doc["created_at"] = datetime.utcnow()
            return self.get_collection(collection_name).insert_one(doc)
        except Exception as e:
            logger.error(f"Insert failed: {e}")
            raise

    def update_doc(self, collection_name: str, query: dict, update: dict, upsert=False):
        try:
            if "$set" not in update:
                update["$set"] = {}
            update["$set"]["updated_at"] = datetime.utcnow()
            return self.get_collection(collection_name).update_one(query, update, upsert=upsert)
        except Exception as e:
            logger.error(f"Update failed: {e}")
            raise

    def close_connection(self):
        if self.client:
            try:
                self.client.close()
                logger.info("MongoDB connection closed.")
            except Exception as e:
                logger.error(f"Error closing MongoDB connection: {e}")

