# constants.py - Shared constants, NO IMPORTS
COLLECTION_NAME = "did_records"
VAULT_PATH_PREFIX = "secret/data/did"
import os
VAULT_TOKEN = os.getenv("VAULT_TOKEN", "hvs.IKACZHrXl34jYjhVOvHr2tpN")
VAULT_ADDR = os.getenv("VAULT_ADDR", "http://10.159.20.87:8200")
VAULT_MOUNT = os.getenv("VAULT_MOUNT", "secret")
VERAMO_BASE = os.getenv("VERAMO_URL", "http://10.159.20.87:4000")
QA_COLLECTION = os.getenv("QA_BENCHMARK_COLLECTION", "benchmark_executions")
#VAULT_ADDR = os.getenv("VAULT_ADDR", "http://10.159.20.87:8200")
#VAULT_TOKEN = ""
#VAULT_MOUNT = os.getenv("VAULT_KV_MOUNT", "secret")
DID_VAULT_PATH_PREFIX = os.getenv("DID_VAULT_PATH_PREFIX", "dids")
API_ACCESS_TOKEN = os.getenv("API_ACCESS_TOKEN", "my-secure-token")
JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key")
MAX_DID_CREATION_WORKERS = int(os.getenv("MAX_DID_CREATION_WORKERS", "6"))
VC_ISSUER_SAFE_LIST = os.getenv("VC_ISSUER_SAFE_LIST", "")  # comma-separated allowed issuers (optional)

# collections / names reused in VC flow
VC_COLLECTION = os.getenv("VC_COLLECTION", "vc_records")
ENCRYPTED_COLLECTION = os.getenv("ENCRYPTED_COLLECTION", "encrypted_docs")
VC_TOKEN_COLLECTION = os.getenv("VC_TOKEN_COLLECTION", "vc_tokens")
FERNET_KEY_FILE = os.getenv("FERNET_KEY_FILE", "fernet.key")
