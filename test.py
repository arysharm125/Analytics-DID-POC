from constants import COLLECTION_NAME
# did_vault_api_sut_updated.py
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Query, Header, Body, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from bson import ObjectId
from datetime import datetime, timedelta
import os, requests, uuid, json, secrets, base64, hvac
from cryptography.fernet import Fernet, InvalidToken
from db_connector import MongoConnector
import threading, time, asyncio
import logging
from utils import generate_did
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from functools import wraps
from typing import List, Optional, Any, Dict
from pydantic import BaseModel
import io
from utils import get_vault_config, init_vault_client
from utils import diff, checksum, merkle_root
import pymongo

#  Import constants (environment configs, collection names)
from constants import (
    VAULT_ADDR,
    VAULT_TOKEN,
    VAULT_MOUNT,
    DID_VAULT_PATH_PREFIX,
    API_ACCESS_TOKEN,
    JWT_SECRET,
    MAX_DID_CREATION_WORKERS,
    VC_ISSUER_SAFE_LIST,
    VC_COLLECTION,
    ENCRYPTED_COLLECTION,
    VC_TOKEN_COLLECTION,
    FERNET_KEY_FILE,
)

# 🔹 Import utility functions from utils.py
from utils import (
    get_vault_config,
    init_vault_client,
    now_iso,
    make_correlation_id,
    clean_mongo_doc,
    sanitize_user_data,
    with_retries,
    detect_kv_version,
    vault_write,
    vault_read,
    vault_list,
    _vault_key_for_did,
    _vault_key_for_iteration,
    _vault_key_for_benchmark,
    store_in_vault_by_keys,
    save_did_record_to_mongo,
    find_existing_did,
    log_audit,
    record_did_change,
    veramo_post,
    veramo_get,
    ensure_issuer_did,
    call_veramo_create_did,
    call_veramo_issue_vc,
    call_veramo_verify_vc,
    extract_jwt_from_vc,
    extract_subject_did,
    create_short_lived_token,
    validate_short_lived_token,
    vault_store_secret,
    vault_fetch_secret,
    load_fernet_key,
    encrypt_data,
    decrypt_data,
    get_from_vault_by_benchmark,
    get_from_vault_by_iteration,
    get_from_vault_by_did,
    _create_child_did_for_iteration,
    create_and_store_mappings,
    normalize_vault_object,
    compute_diff,
    now_timestamp,
    compute_merkle
    )

# Initialize FastAPI app


from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

security = HTTPBasic()

USERNAME = "amd"
PASSWORD = os.getenv("PASSWORD")

def authenticate(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, USERNAME)
    correct_password = secrets.compare_digest(credentials.password, PASSWORD)

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

# ==========================
# Logging
# ==========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("did_vault_api_sut")
logger.setLevel(logging.INFO)

DID_SERVICE_URL = os.getenv("DID_SERVICE_URL", "http://10.159.20.87:4000")

VERAMO_BASE = os.getenv("VERAMO_URL", "http://172.17.0.1:4000")
QA_COLLECTION = os.getenv("QA_BENCHMARK_COLLECTION", "benchmark_executions")

# ✅ Fetch from utils
VAULT_ADDR, VAULT_TOKEN, VAULT_MOUNT = get_vault_config()
vault_client = init_vault_client()

DID_VAULT_PATH_PREFIX = os.getenv("DID_VAULT_PATH_PREFIX", "dids")
API_ACCESS_TOKEN = os.getenv("API_ACCESS_TOKEN")
JWT_SECRET = os.getenv("JWT_SECRET")
MAX_DID_CREATION_WORKERS = int(os.getenv("MAX_DID_CREATION_WORKERS", "6"))
VC_ISSUER_SAFE_LIST = os.getenv("VC_ISSUER_SAFE_LIST", "")
VC_COLLECTION = os.getenv("VC_COLLECTION", "vc_records")
ENCRYPTED_COLLECTION = os.getenv("ENCRYPTED_COLLECTION", "encrypted_docs")
# ==========================
# DB + Vault init
# ==========================
db = MongoConnector()
qa_col = db.get_collection(QA_COLLECTION)
did_vault_col = db.get_collection("did_vault")     # metadata only
audit_log = db.get_collection("did_audit_log")

vault_client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN)

# ==========================
# Requests session with retries for Veramo
# ==========================
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.4, status_forcelist=(502, 503, 504))
adapter = HTTPAdapter(max_retries=retries)
session.mount("http://", adapter)
session.mount("https://", adapter)


# ==========================
# API Models
# ==========================
class CreateSutRequest(BaseModel):
    benchmarkExecutionID: str
    iterationID: Optional[str] = None

class UpdateLevelRequest(BaseModel):
    benchmarkExecutionID: str
    iterationID: str
    level: str

class EntitlementUpdateItem(BaseModel):
    iterationID: str
    entitlement: Dict[str, Any]  # flexible structure, supports nested keys

class BulkEntitlementUpdateRequest(BaseModel):
    benchmarkExecutionID: str
    updates: List[EntitlementUpdateItem]

class VCVerifyRequest(BaseModel):
    # Accept either a raw JWT string or the full VC JSON
    vc_jwt: Optional[str] = None
    vc_obj: Optional[Dict[str, Any]] = None
    # Optional: pass benchmarkExecutionID if you want to check subject mapping
    benchmarkExecutionID: Optional[str] = None
    # Optional: check against a specific DID instead of lookup
    subject_did: Optional[str] = None

class VCVerifyResponse(BaseModel):
    verified_signature: bool
    matches_vault_token: Optional[bool]
    issuer_allowed: Optional[bool]
    subject_matches_db: Optional[bool]
    not_expired: Optional[bool]
    issuer: Optional[str]
    subject: Optional[str]
    details: Dict[str, Any]


# ==========================
# FastAPI App
# ==========================
app = FastAPI(
    title="DID Vault API - SUT (Integrated)",
    version="2025.1",
    dependencies=[Depends(authenticate)]
)
import logging.config
logging.config.fileConfig("logging.ini", disable_existing_loggers=False)

from policy_orchestrator import router as policy_router
app.include_router(policy_router)

from access_gateway import app as access_gateway_app
app.mount("/access", access_gateway_app)

import pymongo

@app.on_event("startup")
async def startup():
    # init vault client and issuer
    try:
        if not vault_client.is_authenticated():
            logger.warning("Vault client not authenticated (token may be missing/invalid)")
        else:
            logger.info("Vault connected and authenticated.")
    except Exception:
        logger.exception("Vault initialization check failed during startup")

    # ensure issuer did
    try:
        ensure_issuer_did()
    except Exception:
        logger.exception("Failed to ensure issuer DID during startup")

    # create TTL index for vc tokens (if permitted)
    try:
        vc_col = db.get_collection(VC_TOKEN_COLLECTION)
        existing_vc_indexes = {idx["name"]: idx for idx in vc_col.list_indexes()}

        if "expires_at_1" not in existing_vc_indexes:
            logger.info("Creating TTL index on vc_tokens.expires_at ...")
            vc_col.create_index(
                [("expires_at", 1)],
                expireAfterSeconds=0,
                name="expires_at_1"
            )
        else:
            logger.info("TTL index for vc tokens already exists")

    except pymongo.errors.OperationFailure as e:
        if e.code == 13:  # Unauthorized
            logger.warning("Skipping TTL index creation — insufficient MongoDB permissions")
        else:
            logger.exception("Mongo OperationFailure during TTL index creation")
    except Exception:
        logger.exception("Unexpected error while creating TTL index for vc tokens")

    # ensure mongo indexes for did_vault and audit_log
    try:
        existing_dv_indexes = list(did_vault_col.list_indexes())
        required_key = {"benchmarkExecutionID": 1, "iterationID": 1}

        composite_exists = any(
            idx.get("key") == required_key
            for idx in existing_dv_indexes
        )

        if composite_exists:
            logger.info("Composite index (benchmarkExecutionID, iterationID) already exists")
        else:
            logger.info("Creating composite index benchmark_iter_idx ...")
            did_vault_col.create_index(
                list(required_key.items()),
                name="benchmark_iter_idx"
            )

        did_vault_col.create_index([("createdAt", -1)], name="createdAt_desc_idx")
        audit_log.create_index([("timestamp", -1)], name="audit_ts_desc_idx")

        logger.info("MongoDB indexes ensured successfully")

    except pymongo.errors.OperationFailure as e:
        if e.code == 85:  # Index exists but name conflict
            logger.warning("Composite index exists with a different name — skipping creation")
        else:
            logger.exception(f"Mongo OperationFailure ensuring DID/Audit indexes: {e}")
    except Exception:
        logger.exception("Unexpected error ensuring Mongo indexes on startup")

# Combined /create-sut-did endpoint (writes only to did_vault/vault)
# -------------------------
@app.post("/create-sut-did", tags=["sut"])
def create_sut_did(req: CreateSutRequest, x_api_token: str = Header(...)):
    if x_api_token != API_ACCESS_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API token")

    benchmarkExecutionID = req.benchmarkExecutionID
    iterationID = req.iterationID

    # ✅ FIRST — Check if master DID already exists (idempotent)
    existing_master = did_vault_col.find_one({
        "benchmarkExecutionID": benchmarkExecutionID,
        "is_master": True
    })

    if existing_master:
        master_did = existing_master["did"]

        # ✅ fetch child iteration DIDs
        children = list(did_vault_col.find(
            {
                "benchmarkExecutionID": benchmarkExecutionID,
                "is_master": False
            },
            {"_id": 0, "iterationID": 1, "did": 1}
        ))

        return {
            "status": "exists",
            "message": "Master DID already initialized",
            "benchmarkExecutionID": benchmarkExecutionID,
            "master_did": master_did,
            "iterations": children,
            "vc_status": "unchanged"
        }

    # ✅ Continue only if DID not created before
    doc = qa_col.find_one({"benchmarkExecutionID": benchmarkExecutionID})
    if not doc:
        raise HTTPException(status_code=404, detail="Benchmark not found in MongoDB")

    # --- Extract iterations ---
    def extract_iterations(d):
        out = []
        if not d:
            return out
        for ri in d.get("resultInfo", []):
            for run in ri.get("runs", []):
                for it in run.get("iterations", []):
                    iid = it.get("iterationID")
                    if iid:
                        out.append(iid)
        return list(dict.fromkeys(out))

    found_iterations = extract_iterations(doc)

    # fallback deep search
    if not found_iterations:
        def deep_find(o):
            res = []
            if isinstance(o, dict):
                if "iterationID" in o and isinstance(o["iterationID"], str):
                    res.append(o["iterationID"])
                for v in o.values():
                    res += deep_find(v)
            elif isinstance(o, list):
                for item in o:
                    res += deep_find(item)
            return res
        found_iterations = list(dict.fromkeys(deep_find(doc)))

    if not found_iterations:
        raise HTTPException(
            status_code=404,
            detail=f"No iterations found under benchmark {benchmarkExecutionID}"
        )

    # --- Mode selection ---
    if iterationID:
        if iterationID not in found_iterations:
            raise HTTPException(
                status_code=404,
                detail=f"Iteration {iterationID} not found under benchmark {benchmarkExecutionID}"
            )
        mode = "single"
        target_iterations = [iterationID]
    else:
        if len(found_iterations) == 1:
            mode = "single"
            target_iterations = [found_iterations[0]]
        else:
            mode = "multi"
            target_iterations = found_iterations

    sut_type = "Single-SUT" if mode == "single" else "Multi-SUT"

    # ✅ Create master + child DIDs (first time only)
    try:
        result = create_and_store_mappings(
            benchmarkExecutionID,
            target_iterations,
            sut_type
        )
    except Exception as e:
        logger.exception("Failed to create DIDs: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create SUT DIDs: {e}")

    master = result.get("master_did")

    # ✅ store master marker in Mongo
    did_vault_col.update_one(
        {"benchmarkExecutionID": benchmarkExecutionID},
        {
            "$set": {
                "did": master,
                "is_master": True,
                "sut_type": sut_type,
                "created_at": now_iso()
            }
        },
        upsert=True
    )

    # ✅ Issue parent + child VCs
    issuer_did = ensure_issuer_did()

    issued_parent_vc = False
    issued_child_vcs = []

    try:
        jwt = call_veramo_issue_vc(issuer_did, master, benchmarkExecutionID)
        vault_store_secret(f"vc_tokens/{master}", {"vc_jwt": jwt}, lifespan_minutes=10)
        issued_parent_vc = True
    except Exception:
        logger.exception("Failed issuing parent VC for %s", master)

    for entry in result.get("iterations", []):
        cid = entry["did"]
        iteration_id = entry["iterationID"]
        try:
            jwt = call_veramo_issue_vc(issuer_did, cid, iteration_id)
            vault_store_secret(f"vc_tokens/{cid}", {"vc_jwt": jwt}, lifespan_minutes=10)
            issued_child_vcs.append({
                "iterationID": iteration_id,
                "did": cid,
                "vc_issued": True
            })
        except Exception:
            logger.exception("Failed issuing VC for %s", cid)
            issued_child_vcs.append({
                "iterationID": iteration_id,
                "did": cid,
                "vc_issued": False
            })

    return JSONResponse({
        "status": "created",
        "benchmarkExecutionID": benchmarkExecutionID,
        "mode": mode,
        "master_did": master,
        "iterations": result.get("iterations", []),
        "vc_status": {
            "parent_vc_issued": issued_parent_vc,
            "sut_vcs": issued_child_vcs
        }
    })


from fastapi import APIRouter, HTTPException
from bson import json_util
import json

def _extract_iteration_from_benchmark(doc: dict, iteration_id: str):
    """
    Helper: from full benchmark_executions JSON, find specific iteration object
    under resultInfo -> runs -> iterations.
    """
    if not doc:
        return None
    for ri in doc.get("resultInfo", []):
        for run in ri.get("runs", []):
            for it in run.get("iterations", []):
                if isinstance(it, dict) and it.get("iterationID") == iteration_id:
                    return it
    return None

@app.post("/resolve", tags=["did"])
def resolve_did(request: dict):
    """
    Resolve a DID:

    - If it's a master DID (iterationID is null in did_vault):
        -> returns full benchmark_executions JSON in `benchmark_doc`.

    - If it's a child DID (iterationID set in did_vault):
        -> returns ONLY that specific iteration object in `iteration_doc`,
           but also indicates benchmarkExecutionID and did.
    """
    did = request.get("did")
    if not did:
        raise HTTPException(status_code=400, detail="DID is required in request body")

    # Look in main did_vault collection
    rec = did_vault_col.find_one({"did": did})
    source = "mongo"

    # Fallback: try Vault by DID
    if not rec:
        try:
            # This returns decrypted full payload that was stored in Vault
            # using store_encrypted_in_vault (full benchmark_executions JSON).
            from utils import get_encrypted_payload_from_vault, decrypt_data
            enc = get_encrypted_payload_from_vault(did)
            full_payload = decrypt_data(enc)
            # emulate rec shape
            rec = {
                "did": did,
                "benchmarkExecutionID": full_payload.get("benchmarkExecutionID"),
                "iterationID": full_payload.get("iterationID"),
                "data": full_payload
            }
            source = "vault"
        except Exception:
            rec = None

    if not rec:
        raise HTTPException(status_code=404, detail=f"DID {did} not found in did_vault or Vault")

    benchmarkExecutionID = rec.get("benchmarkExecutionID")
    iterationID = rec.get("iterationID")
    full_doc = rec.get("data") or {}

    if iterationID:
        # Child DID -> extract only that iteration from full benchmark JSON
        iteration_doc = _extract_iteration_from_benchmark(full_doc, iterationID)
        return json.loads(json_util.dumps({
            "did": did,
            "source": source,
            "mode": "child",
            "benchmarkExecutionID": benchmarkExecutionID,
            "iterationID": iterationID,
            "iteration_doc": iteration_doc
        }))
    else:
        # Master DID -> return full benchmark document
        return json.loads(json_util.dumps({
            "did": did,
            "source": source,
            "mode": "master",
            "benchmarkExecutionID": benchmarkExecutionID,
            "benchmark_doc": full_doc
        }))


from pydantic import BaseModel
from typing import Dict, Any, Optional

class DIDAppendRequest(BaseModel):
    benchmarkExecutionID: str
    iterationID: str
    data: Dict[str, Any]

from fastapi import HTTPException, Query, Request
from utils import validate_amd_email


@app.post("/append-did", tags=["sut"])
async def append_did(
    body: DIDAppendRequest,
    update_message: str = Query(...),
    updated_by: str = Query(...)
):

    # ---------------- EMAIL VALIDATION ---------------------
    validate_amd_email(updated_by)

    benchmarkExecutionID = body.benchmarkExecutionID
    iterationID = body.iterationID
    incoming_data = body.data or {}

    if not benchmarkExecutionID:
        raise HTTPException(400, "benchmarkExecutionID is required")

    # ---------------- FETCH RECORD -------------------------
    record = did_vault_col.find_one({
        "benchmarkExecutionID": benchmarkExecutionID,
        "iterationID": iterationID
    })

    if not record:
        raise HTTPException(404, "Record not found for provided benchmarkExecutionID and iterationID")

    old_data = record.get("data") or {}
    old_did = record.get("did")

    # ---------------- MERGE OLD + NEW DATA ------------------
    new_data = {**old_data, **incoming_data}

    # ---------------- NEW DID FROM VERAMO -------------------
    new_did = generate_did()  # << your original Veramo call

    # ---------------- COMPUTE DIFF --------------------------
    diff_log = compute_diff(old_data, new_data)

    # ---------------- READ CHAIN ----------------------------
    chain_path = f"{iterationID}/chain"
    raw_chain = vault_read(VAULT_MOUNT, chain_path)

    if raw_chain is None:
        chain_list = []
    elif isinstance(raw_chain, list):
        chain_list = raw_chain
    elif isinstance(raw_chain, dict):
        chain_list = raw_chain.get("chain", []) or []
    else:
        chain_list = []

    # ---------------- APPEND NEW DID TO CHAIN --------------
    chain_list.append(new_did)

    # ---------------- COMPUTE MERKLE ROOT -------------------
    merkle = merkle_root(chain_list)

    # ---------------- WRITE CHAIN BACK TO VAULT -------------
    vault_write(VAULT_MOUNT, chain_path, {"chain": chain_list})

    # ---------------- STORE VERSION SNAPSHOT ----------------
    snapshot_payload = {
        "did": new_did,
        "previous_did": old_did,
        "timestamp": now_timestamp(),
        "benchmarkExecutionID": benchmarkExecutionID,
        "iterationID": iterationID,

        # FULL CURRENT DATA
        "data": new_data,

        # FULL PREVIOUS DATA
        "previous_data": old_data,

        # DIFF BETWEEN THEM
        "diff": diff_log,

        "updated_by": updated_by,
        "update_message": update_message,

        "merkle_root": merkle
    }

    vault_write(
        VAULT_MOUNT,
        f"{iterationID}/{new_did}",
        {"data": snapshot_payload}  # KV v2 format required
    )

    # ---------------- UPDATE MONGO (LATEST VERSION ONLY) ----
    did_vault_col.update_one(
        {
            "benchmarkExecutionID": benchmarkExecutionID,
            "iterationID": iterationID
        },
        {
            "$set": {
                "did": new_did,
                "data": new_data,
                "previous_did": old_did,
                "merkle_root": merkle,
                "last_updated": now_timestamp(),
                "updated_by": updated_by,
                "update_message": update_message
            }
        }
    )

    # ---------------- RESPONSE ------------------------------
    return {
        "status": "updated",
        "benchmarkExecutionID": benchmarkExecutionID,
        "iterationID": iterationID,
        "new_did": new_did,
        "previous_did": old_did,
        "merkle_root": merkle,
        "chain_length": len(chain_list),
        "diff": diff_log
    }


#    """
#    benchmarkExecutionID = req.benchmarkExecutionID
#    iterationID = req.iterationID
#    new_level = req.level
#
#    # Ensure the iteration exists (read only from QA collection if needed)
#    doc = qa_col.find_one({"benchmarkExecutionID": benchmarkExecutionID})
#    if not doc:
#        raise HTTPException(status_code=404, detail="Benchmark not found")
#
#    # verify iteration exists in benchmark (READ)
#    found = False
#    def check_iter(obj):
#        nonlocal found
#        if isinstance(obj, dict):
#            if obj.get("iterationID") == iterationID:
#                found = True
#                return
#            for v in obj.values():
#                check_iter(v)
#        elif isinstance(obj, list):
#            for i in obj:
#                check_iter(i)
#    check_iter(doc)
#    if not found:
#        raise HTTPException(status_code=404, detail=f"Iteration {iterationID} not found in benchmark")
#
#    # UPDATE only in did_vault collection
#    try:
#        res = did_vault_col.update_one(
#            {"benchmarkExecutionID": benchmarkExecutionID, "iterationID": iterationID},
#            {"$set": {"level": new_level, "last_updated": now_iso()}},
#            upsert=True
#        )
#        # Also update Vault per-iteration path for consistency
#        try:
#            iter_path = _vault_key_for_iteration(iterationID)
#            existing = {}
#            try:
#                existing = vault_read(VAULT_MOUNT, iter_path)
#            except Exception:
#                existing = {}
#            merged = {**existing, "iterationID": iterationID, "benchmarkExecutionID": benchmarkExecutionID, "level": new_level, "last_updated": now_iso()}
#            vault_write(VAULT_MOUNT, iter_path, merged)
#        except Exception:
#            logger.exception("Failed to sync iteration level to Vault (non-blocking)")
#    except Exception as e:
#        logger.exception("Failed to update level in did_vault: %s", e)
#        raise HTTPException(status_code=500, detail="Failed to update entitlement level")
#
#    return {
#        "benchmarkExecutionID": benchmarkExecutionID,
#        "iterationID": iterationID,
#        "new_level": new_level,
#        "status": "updated"
#    }
#
## -------------------------
## Issue VC (kept as previous logic)
## -------------------------
#@app.post("/bulk-entitlement-update", tags=["sut"])
#def bulk_entitlement_update(req: BulkEntitlementUpdateRequest):
#    """
#    Bulk entitlement update based only on benchmarkExecutionID.
#    - Applies the entitlement update to all iterations inside the benchmark.
#    - Writes ONLY to did_vault (no writes to benchmark_executions).
#    """
#
#    benchmarkExecutionID = req.benchmarkExecutionID
#
#    # Combine all entitlement updates into one merged object
#    combined_entitlement = {}
#    for item in req.updates:
#        combined_entitlement.update(item.entitlement)
#
#    # Fetch existing benchmark record (READ only)
#    doc = qa_col.find_one({"benchmarkExecutionID": benchmarkExecutionID})
#    if not doc:
#        raise HTTPException(status_code=404, detail="Benchmark not found")
#
#    # Determine which iterationIDs exist in benchmark (READ)
#    iteration_ids = []
#    def gather_iter(obj):
#        if isinstance(obj, dict):
#            if "iterationID" in obj:
#                iteration_ids.append(obj["iterationID"])
#            for v in obj.values():
#                gather_iter(v)
#        elif isinstance(obj, list):
#            for i in obj:
#                gather_iter(i)
#    gather_iter(doc)
#
#    if not iteration_ids:
#        raise HTTPException(status_code=404, detail="No iterations found for entitlement update")
#
#    updated_iterations = []
#    # Apply entitlement updates to did_vault entries for each iterationID
#    for it in iteration_ids:
#        try:
#            did_vault_col.update_one(
#                {"benchmarkExecutionID": benchmarkExecutionID, "iterationID": it},
#                {"$set": {"entitlement": combined_entitlement, "entitlement_updated_at": now_iso()}},
#                upsert=True
#            )
#            # also sync to per-iteration Vault path
#            try:
#                iter_path = _vault_key_for_iteration(it)
#                existing = {}
#                try:
#                    existing = vault_read(VAULT_MOUNT, iter_path)
#                except Exception:
#                    existing = {}
#                merged = {**existing, "iterationID": it, "benchmarkExecutionID": benchmarkExecutionID, "entitlement": combined_entitlement, "entitlement_updated_at": now_iso()}
#                vault_write(VAULT_MOUNT, iter_path, merged)
#            except Exception:
#                logger.exception("Failed to sync entitlement to Vault for iteration %s (non-blocking)", it)
#
#            updated_iterations.append(it)
#        except Exception as e:
#            logger.exception("Failed to update entitlement for iteration %s: %s", it, e)
#
#    if not updated_iterations:
#        raise HTTPException(status_code=500, detail="Failed to update any iterations")
#
#    return {
#        "benchmarkExecutionID": benchmarkExecutionID,
#        "applied_entitlement": combined_entitlement,
#        "updated_iterations": updated_iterations,
#        "total_iterations_updated": len(updated_iterations),
#        "status": "success"
#    }
#

@app.post("/issue-vc/{did}")
def issue_vc_for_did(did: str, token_lifespan: int = 10):
    issuer_did = ensure_issuer_did()

    # try to find mapping in did_vault by did
    rec = did_vault_col.find_one({"did": did}) or did_vault_col.find_one({"master_did": did})
    if not rec:
        # fallback: search QA collection for mapping (read-only)
        rec = qa_col.find_one({
            "benchmarkExecutionID": {"$exists": True},
            "$or": [
                {"resultInfo.runs.iterations.did": did},
                {"resultInfo.runs.iterations.iterationID": did}
            ]
        })
    if not rec:
        raise HTTPException(404, f"DID {did} not found")

    parent_id = rec.get("benchmarkExecutionID") or str(rec.get("_id"))

    # Get VC from Vault if already issued, otherwise issue a new one
    vault_data = vault_fetch_secret(f"vc_tokens/{did}")
    jwt_token = vault_data.get("vc_jwt") if vault_data else None

    if not jwt_token:
        # issue new VC via Veramo
        jwt_token = call_veramo_issue_vc(issuer_did, did, parent_id)

    # store / refresh VC JWT in Vault (vc_tokens/{did})
    vault_store_secret(f"vc_tokens/{did}", {"vc_jwt": jwt_token}, lifespan_minutes=token_lifespan)

    # NO MORE encrypted_doc in Mongo; encrypted data is handled by Vault at dids/by_did/<did>

    # short-lived token stored in Vault (vc_tokens/{token})
    token = create_short_lived_token(did, jwt_token, lifespan_minutes=token_lifespan)

    return {
        "did": did,
        "token": token,
        "expires_in_minutes": token_lifespan
    }

# -------------------------
# Download VC
# -------------------------
@app.get("/vc/download/{did}")
def download_vc(did: str, token_lifespan: int = 10):
    vault_data = vault_fetch_secret(f"vc_tokens/{did}")
    vc_jwt = vault_data.get("vc_jwt")
    if not vc_jwt:
        raise HTTPException(404, f"No VC found in Vault for DID {did}")

    token = create_short_lived_token(did, vc_jwt, lifespan_minutes=token_lifespan)
    response_data = {
        "did": did,
        "vc": {"format": "jwt", "jwt": vc_jwt},
        "token": token,
        "expires_in_minutes": token_lifespan
    }

    return StreamingResponse(
        io.BytesIO(json.dumps(response_data, indent=2).encode("utf-8")),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={did.replace(':','_')}_vc.json"}
    )

@app.post("/vc/upload-verify")
def upload_and_verify_vc(file: UploadFile = File(...)):
    # -------------------------
    # Read + parse uploaded JSON
    # -------------------------
    content = file.file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")

    try:
        vc_content = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {str(e)}")
    finally:
        file.file.close()

    jwt_token = extract_jwt_from_vc(vc_content)
    if not jwt_token:
        raise HTTPException(400, "JWT missing in uploaded VC")

    # -------------------------
    # Determine subject DID
    # -------------------------
    subject_did = (
        vc_content.get("did")
        or extract_subject_did(vc_content)
        or vc_content.get("vc", {}).get("credentialSubject", {}).get("id")
    )

    if not subject_did:
        raise HTTPException(404, "Cannot determine DID from VC")

    # -------------------------
    # 1) Verify VC token stored in Vault
    # -------------------------
    vault_data = vault_fetch_secret(f"vc_tokens/{subject_did}")
    vault_data = normalize_vault_object(vault_data)

    vault_jwt = vault_data.get("vc_jwt") if vault_data else None
    if not vault_jwt:
        raise HTTPException(404, f"No VC entry in Vault for DID {subject_did}")

    if vault_jwt != jwt_token:
        raise HTTPException(403, f"Uploaded VC does not match stored VC for {subject_did}")

    # -------------------------
    # 2) Cryptographic verification
    # -------------------------
    verification_result = call_veramo_verify_vc(jwt_token)
    if not verification_result.get("verified", False):
        raise HTTPException(400, "VC verification failed")

    # -------------------------
    # 3) Fetch FULL DID RECORD from Vault
    # -------------------------
    try:
        did_obj = get_from_vault_by_did(subject_did)
    except HTTPException:
        raise HTTPException(404, f"No DID record found in Vault for {subject_did}")
    except Exception as e:
        raise HTTPException(500, f"Error reading Vault for DID {subject_did}: {e}")

    did_obj = normalize_vault_object(did_obj)

    # -------------------------
    # 4) Fetch chain history
    # -------------------------
    chain_path = did_obj.get("iterationID")
    chain_data = {}

    if chain_path:
        try:
            raw = vault_read(VAULT_MOUNT, f"{chain_path}/chain") or {}
            raw = normalize_vault_object(raw)
            chain_data = raw.get("chain", [])
        except Exception:
            chain_data = []

    # -------------------------
    # 5) Fetch full Mongo stored record
    # -------------------------
    mongo_record = did_vault_col.find_one(
        {"did": subject_did},
        {"_id": 0}
    )

    # -------------------------
    # 6) If encrypted exists → decrypt
    # -------------------------
    decrypted = None
    encrypted_payload = did_obj.get("encrypted")

    if encrypted_payload:
        try:
            decrypted = decrypt_data(encrypted_payload)
        except Exception as e:
            raise HTTPException(500, f"Failed to decrypt stored data: {e}")

    return {
        "did": subject_did,
        "verified": True,
        "full_record": {
            "vault_record": did_obj,
            "chain": chain_data,
            "mongo_record": mongo_record,
            "decrypted_data": decrypted
        },
        "vault_check": "VC matched with Vault and verified successfully",
        "message": "Full DID record retrieved successfully"
    }


# -------------------------
# Upload & Verify VC file
# -------------------------

@app.post("/vc/verify", tags=["vc"], response_model=VCVerifyResponse)
def verify_vc(req: VCVerifyRequest):
    """
    Verify VC signature and basic integrity checks:
     - cryptographic signature via Veramo
     - matches stored VC token in Vault (if present)
     - issuer allowed (VC_ISSUER_SAFE_LIST)
     - subject mapping exists in DB (optional)
     - expiration check
    """
    # Validate input
    if not req.vc_jwt and not req.vc_obj:
        raise HTTPException(status_code=400, detail="Either vc_jwt or vc_obj must be provided")

    # ✅ FIX: Extract jwt_token properly from request
    jwt_token = req.vc_jwt
    if not jwt_token:
        # fallback if only vc_obj was provided and it includes JWT
        jwt_token = extract_jwt_from_vc(req.vc_obj)
        if not jwt_token:
            raise HTTPException(status_code=400, detail="Could not determine JWT from request")

    # 1) Cryptographic verification via Veramo
    try:
        veramo_resp = call_veramo_verify_vc(jwt_token)
    except Exception as e:
        logger.exception("Veramo verify error: %s", e)
        raise HTTPException(status_code=500, detail=f"Veramo verification failed: {e}")

    # Interpret veramo_resp — expected structure depends on your Veramo setup.
    verified_signature = False
    try:
        if isinstance(veramo_resp, dict):
            if veramo_resp.get("verified") is True:
                verified_signature = True
            elif isinstance(veramo_resp.get("results"), list):
                verified_signature = any(r.get("verified") or r.get("ok") for r in veramo_resp["results"])
    except Exception:
        verified_signature = False

    # 2) Extract issuer & subject from the VC (from jwt or vc_obj)
    issuer = None
    subject = None
    exp_ok = None
    try:
        payload = veramo_resp.get("payload") if isinstance(veramo_resp, dict) else None

        if payload:
            issuer = payload.get("iss") or (payload.get("vc") or {}).get("issuer")
            subject = payload.get("sub")
            exp = payload.get("exp")

            import time
            if exp:
                exp_ok = (int(exp) > int(time.time()))
            else:
                vc = payload.get("vc") or {}
                expirationDate = vc.get("expirationDate") or (vc.get("credentialSubject") or {}).get("expirationDate")
                if expirationDate:
                    from dateutil import parser
                    exp_ok = parser.parse(expirationDate) > datetime.utcnow()
        elif req.vc_obj:
            vc = req.vc_obj
            issuer = vc.get("issuer") or (vc.get("vc") or {}).get("issuer")
            subj = vc.get("credentialSubject") or vc.get("vc", {}).get("credentialSubject")
            if isinstance(subj, dict):
                subject = subj.get("id") or subj.get("did")
            expirationDate = vc.get("expirationDate") or (vc.get("vc") or {}).get("expirationDate")
            if expirationDate:
                from dateutil import parser
                exp_ok = parser.parse(expirationDate) > datetime.utcnow()
    except Exception as e:
        logger.debug("Failed to extract payload info: %s", e)

    # 3) Compare to stored token in Vault (if subject/did present)
    matches_vault_token = None
    if subject:
        try:
            stored = get_vault_stored_vc_for_did(subject)
            if stored:
                matches_vault_token = (stored == jwt_token)
        except Exception as e:
            logger.debug("Vault compare failed: %s", e)

    # 4) Issuer whitelist check
    issuer_allowed = is_issuer_allowed(issuer) if issuer else None

    # 5) Subject mapping check (optional)
    subject_matches_db = None
    if req.benchmarkExecutionID and subject:
        try:
            coll = db.get_collection("benchmark_executions")
            q = {
                "benchmarkExecutionID": req.benchmarkExecutionID,
                "$or": [
                    {"master_did": subject},
                    {"resultInfo.runs.iterations.did": subject},
                    {"resultInfo.runs.iterations.iterationID": subject}
                ],
            }
            found = coll.find_one(q)
            subject_matches_db = bool(found)
        except Exception as e:
            logger.debug("DB subject mapping check failed: %s", e)

    # 6) Build and return
    details = {
        "veramo_raw_response": veramo_resp,
        "extracted_issuer": issuer,
        "extracted_subject": subject,
        "expiration_ok": exp_ok
    }

    resp = {
        "verified_signature": bool(verified_signature),
        "matches_vault_token": matches_vault_token,
        "issuer_allowed": issuer_allowed,
        "subject_matches_db": subject_matches_db,
        "not_expired": exp_ok,
        "issuer": issuer,
        "subject": subject,
        "details": details
    }

    return json.loads(json_util.dumps(resp))


def normalize_vault_object(obj):
    # Handles KV v1, KV v2, lists, None
    if not obj:
        return {}
    if isinstance(obj, list) and len(obj) > 0:
        obj = obj[0]
    if "data" in obj:
        inner = obj.get("data")
        if isinstance(inner, dict) and "data" in inner:
            return inner["data"]
        return inner
    return obj

from typing import Optional, List, Dict, Any
from fastapi import Query
def vault_read_raw(path: str):
    """
    Direct raw Vault GET for KV2: no key mapping performed.
    """
    try:
        result = client.secrets.kv.v2.read_secret_version(
            path=path.replace("secret/", ""),
            mount_point="secret"
        )
        return result
    except Exception:
        return {}
@app.get("/did-history", tags=["sut"])
def get_did_history(
    benchmarkExecutionID: str = Query(...),
    iterationID: Optional[str] = Query(None)
):
    """
    Return full DID history using Vault DID snapshots 
    following `previous_did` chain.
    """

    # ---------- Find correct iteration ----------
    if iterationID:
        record = did_vault_col.find_one({
            "benchmarkExecutionID": benchmarkExecutionID,
            "iterationID": iterationID
        })
    else:
        matches = list(did_vault_col.find({"benchmarkExecutionID": benchmarkExecutionID}, {"iterationID": 1}))
        ids = [m["iterationID"] for m in matches if m.get("iterationID")]
        ids = list(dict.fromkeys(ids))

        if not ids:
            raise HTTPException(404, "No iterations found")
        if len(ids) > 1:
            raise HTTPException(400, "Multiple iterations found — specify iterationID")

        iterationID = ids[0]
        record = did_vault_col.find_one({
            "benchmarkExecutionID": benchmarkExecutionID,
            "iterationID": iterationID
        })

    if not record:
        raise HTTPException(404, "Record not found")

    # ---------- Traverse DID chain backwards ----------
    chain = []
    current_did = record.get("did")

    while current_did:
        chain.append(current_did)

        try:
            result = vault_client.secrets.kv.v2.read_secret_version(
                path=f"{iterationID}/{current_did}",
                mount_point="secret"
            )
            data_obj = result.get("data", {}).get("data", {})
            previous_did = data_obj.get("previous_did")
        except Exception:
            previous_did = None

        if not previous_did or previous_did in chain:
            break
        current_did = previous_did

    # Remove duplicates, keep correct order
    chain = list(dict.fromkeys(chain))

    # ---------- Fetch snapshot for each DID ----------
    history = []

    for did in chain:
        try:
            secret_path = f"{iterationID}/{did}"
            snap_raw = vault_client.secrets.kv.v2.read_secret_version(
                path=secret_path,
                mount_point="secret"
            )

            data_obj = snap_raw.get("data", {}).get("data", {}) if snap_raw else {}

            history.append({
                "did": data_obj.get("did", did),
                "previous_did": data_obj.get("previous_did"),
                "timestamp": data_obj.get("timestamp"),
                "benchmarkExecutionID": data_obj.get("benchmarkExecutionID", benchmarkExecutionID),
                "iterationID": data_obj.get("iterationID", iterationID),
                "data": data_obj.get("data"),
                "diff": data_obj.get("diff"),
                "merkle_root": data_obj.get("merkle_root"),
                "update_message": data_obj.get("update_message"),
                "updated_by": data_obj.get("updated_by"),
            })

        except Exception as e:
            history.append({"did": did, "error": str(e)})

    # Sort versions oldest → newest
    history_sorted = sorted(history, key=lambda x: x.get("timestamp") or "")

    # ---------- Response ----------
    return {
        "benchmarkExecutionID": benchmarkExecutionID,
        "iterationID": iterationID,
        "current": {
            "did": record.get("did"),
            "data": record.get("data"),
            "merkle_root": record.get("merkle_root"),
            "last_updated": record.get("last_updated"),
        },
        "chain": chain,
        "versions": history_sorted,
        "total_versions": len(history_sorted)
    }

@app.get("/search-sut", tags=["sut"])
def search_sut(
    benchmarkExecutionID: Optional[str] = Query(None),
    iterationID: Optional[str] = Query(None),
    x_api_token: str = Header(...)
):
    if x_api_token != API_ACCESS_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API token")

    if not benchmarkExecutionID and not iterationID:
        raise HTTPException(status_code=400, detail="Provide benchmarkExecutionID or iterationID")

    if iterationID:
        return fetch_by_iteration(iterationID)

    if benchmarkExecutionID:
        match = did_vault_col.find_one(
            {"benchmarkExecutionID": benchmarkExecutionID},
            {"iterationID": 1, "_id": 0}
        )
        if not match:
            raise HTTPException(404, "No mapping found")

        iterationID = match["iterationID"]
        return fetch_by_iteration(iterationID)


def fetch_by_iteration(iterationID: str):
    """
    Fetch all DID records from Vault under secret/<iterationID>/…
    """
    try:
        # List folder
        keys_resp = client.secrets.kv.v2.list_secrets(
            path=iterationID, mount_point="secret"
        )
        keys = keys_resp.get("data", {}).get("keys", [])

        did_records = []

        for key in keys:
            if key.endswith("/"):  # Skip inner folders if any
                continue

            result = client.secrets.kv.v2.read_secret_version(
                path=f"{iterationID}/{key}", mount_point="secret"
            )
            data = result.get("data", {}).get("data", {})
            did_records.append(data)

        if did_records:
            return {"source": "vault", "records": did_records}

    except Exception:
        pass  # fallback below

    # Fallback: Mongo
    recs = list(did_vault_col.find({"iterationID": iterationID}, {"_id": 0}))
    if recs:
        return {"source": "mongo", "records": recs}

    raise HTTPException(404, "No records found")

# Search SUT endpoint (benchmark/iteration)
# -------------------------
#@app.get("/search-sut", tags=["sut"])
#def search_sut(benchmarkExecutionID: Optional[str] = Query(None), iterationID: Optional[str] = Query(None), x_api_token: str = Header(...)):
#    if x_api_token != API_ACCESS_TOKEN:
#        raise HTTPException(status_code=401, detail="Invalid API token")
#    if not benchmarkExecutionID and not iterationID:
#        raise HTTPException(status_code=400, detail="Provide benchmarkExecutionID or iterationID")
#
#    if iterationID:
#        try:
#            mapping = get_from_vault_by_iteration(iterationID)
#            return {"source": "vault", "mapping": mapping}
#        except HTTPException:
#            rec = did_vault_col.find_one({"iterationID": iterationID})
#            if rec:
#                return {"source": "mongo", "mapping": clean_mongo_doc(rec)}
#            raise
#
#    if benchmarkExecutionID:
#        try:
#            master = get_from_vault_by_benchmark(benchmarkExecutionID)
#            return {"source": "vault", "mapping": master}
#        except HTTPException:
#            recs = list(did_vault_col.find({"benchmarkExecutionID": benchmarkExecutionID}, {"_id": 0}))
#            if recs:
#                return {"source": "mongo", "mappings": clean_mongo_doc(recs)}
#            raise HTTPException(status_code=404, detail="No mapping found for provided benchmark/iteration")

# -------------------------
# Health
# -------------------------
@app.get("/health", tags=["health"])
def health():
    try:
        vault_ok = vault_client.is_authenticated()
    except Exception:
        vault_ok = False
    return {"status": "ok", "vault_authenticated": vault_ok}

# EOF

