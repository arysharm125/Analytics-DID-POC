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
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from functools import wraps
from typing import List, Optional, Any, Dict
from pydantic import BaseModel
import io

from utils import (
    COLLECTION_NAME, ENCRYPTED_COLLECTION, VC_TOKEN_COLLECTION, VERAMO_BASE, QA_COLLECTION, now_iso, make_correlation_id, clean_mongo_doc, sanitize_user_data, with_retries, detect_kv_version, vault_write, vault_read, vault_list, _vault_key_for_did, _vault_key_for_iteration, _vault_key_for_benchmark, store_in_vault_by_keys, save_did_record_to_mongo, find_existing_did, log_audit, record_did_change, veramo_post, veramo_get, ensure_issuer_did, call_veramo_create_did, call_veramo_issue_vc, call_veramo_verify_vc, extract_jwt_from_vc, extract_subject_did, create_short_lived_token, validate_short_lived_token, vault_store_secret, vault_fetch_secret, load_fernet_key, encrypt_data, decrypt_data, get_from_vault_by_benchmark, get_from_vault_by_iteration, get_from_vault_by_did, _create_child_did_for_iteration, create_and_store_mappings 
)

#from utils import COLLECTION_NAME, save_did_record_to_mongo

app = FastAPI()
# ==========================
# Logging
# ==========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("did_vault_api_sut")
logger.setLevel(logging.INFO)

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

# ==========================
# FastAPI App
# ==========================
app = FastAPI(title="DID Vault API - SUT (Integrated)", version="2025.1")

@app.on_event("startup")
async def startup():
    # init vault client and issuer
    try:
        # ensure vault client is usable
        if not vault_client.is_authenticated():
            logger.warning("Vault client not authenticated (token may be missing/invalid)")
        else:
            logger.info("Vault connected and authenticated.")
    except Exception:
        logger.exception("Vault initialization check failed during startup")

    try:
        ensure_issuer_did()
    except Exception:
        logger.exception("Failed to ensure issuer DID during startup")

    # index for token cleanup
    try:
        db.get_collection(VC_TOKEN_COLLECTION).create_index("expires_at", expireAfterSeconds=0)
    except Exception:
        logger.exception("Failed to create TTL index for vc tokens")

    # ensure mongo indexes for did_vault and audit_log
    try:
        did_vault_col.create_index([("did", 1)], unique=True)
        did_vault_col.create_index([("benchmarkExecutionID", 1), ("iterationID", 1)], unique=False)
        did_vault_col.create_index([("createdAt", -1)])
        audit_log.create_index([("timestamp", -1)])
    except Exception:
        logger.exception("Failed to ensure Mongo indexes on startup")

# -------------------------
# REPLACED: Combined /create-sut-did endpoint
# -------------------------
@app.post("/create-sut-did", tags=["sut"])
def create_sut_did(req: CreateSutRequest, x_api_token: str = Header(...)):
    """
    Unified endpoint to create SUT DIDs.
    - Input: benchmarkExecutionID (required) and optional iterationID.
    - Automatically decides single vs multi SUT if benchmark has multiple iterationIDs.
    - Returns master DID and child DIDs created / reused.
    """
    if x_api_token != API_ACCESS_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API token")

    benchmarkExecutionID = req.benchmarkExecutionID
    iterationID = req.iterationID

    # Fetch benchmark doc
    doc = qa_col.find_one({"benchmarkExecutionID": benchmarkExecutionID})
    if not doc:
        raise HTTPException(status_code=404, detail="Benchmark not found in MongoDB")

    # Extract iteration IDs from resultInfo -> runs -> iterations
    def extract_iterations_from_doc(d):
        ids = []
        if not d:
            return ids
        # resultInfo may be a list with runs nested
        for ri in d.get("resultInfo", []):
            runs = ri.get("runs", [])
            for r in runs:
                for it in r.get("iterations", []):
                    iid = it.get("iterationID")
                    if iid:
                        ids.append(iid)
        # dedupe preserving order
        seen = set(); out = []
        for i in ids:
            if i not in seen:
                seen.add(i); out.append(i)
        return out

    iteration_ids_all = extract_iterations_from_doc(doc)
    logger.debug("Found iteration IDs for benchmark %s: %s", benchmarkExecutionID, iteration_ids_all)

    if not iteration_ids_all:
        # fallback: try to find iterationID under other keys e.g., runs.iterations at top-level
        def generic_extract(o):
            out = []
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "iterationID" and isinstance(v, str):
                        out.append(v)
                    else:
                        out += generic_extract(v)
            elif isinstance(o, list):
                for item in o:
                    out += generic_extract(item)
            return out
        iteration_ids_all = list(set(generic_extract(doc)))

    # determine mode
    mode = "single" if len(iteration_ids_all) <= 1 else "multi"

    # if iterationID provided, validate presence
    if iterationID and iterationID not in iteration_ids_all:
        raise HTTPException(status_code=404, detail=f"Iteration {iterationID} not found in benchmark")

    # choose target iterations
    if mode == "single":
        # if iterationID provided, use it; else use the only iteration present if exists
        if iterationID:
            target_iterations = [iterationID]
        elif iteration_ids_all:
            target_iterations = [iteration_ids_all[0]]
        else:
            # No iteration IDs available -- cannot proceed
            raise HTTPException(status_code=400, detail="No iteration IDs found to create SUT DID")
    else:
        # multi - if user passed a specific iterationID, generate for that one only, else all
        if iterationID:
            target_iterations = [iterationID]
        else:
            target_iterations = iteration_ids_all

    sut_type = "Single-SUT" if mode == "single" else "Multi-SUT"

    # call existing create_and_store_mappings to create master + child dIDs
    try:
        result = create_and_store_mappings(benchmarkExecutionID, target_iterations, sut_type)
    except Exception as e:
        logger.exception("Failed to create SUT DIDs for benchmark %s: %s", benchmarkExecutionID, e)
        raise HTTPException(status_code=500, detail=f"Failed to create SUT DIDs: {e}")

    # After DID creation, optionally issue VCs (both parent and per-SUT)
    issuer_did = ensure_issuer_did()
    parent_did = result.get("master_did")
    issued_parent_vc = False
    issued_child_vcs = []

    # Issue parent VC for the master DID
    try:
        parent_jwt = call_veramo_issue_vc(issuer_did, parent_did, benchmarkExecutionID)
        vault_store_secret(f"vc_tokens/{parent_did}", {"vc_jwt": parent_jwt}, lifespan_minutes=10)
        issued_parent_vc = True
    except Exception:
        logger.exception("Failed to issue parent VC for master DID %s", parent_did)

    # Issue VCs for each child DID (iteration-level)
    for entry in result.get("iterations", []):
        child_did = entry.get("did")
        iteration_id = entry.get("iterationID")
        try:
            child_jwt = call_veramo_issue_vc(issuer_did, child_did, iteration_id or benchmarkExecutionID)
            vault_store_secret(f"vc_tokens/{child_did}", {"vc_jwt": child_jwt}, lifespan_minutes=10)
            issued_child_vcs.append({"iterationID": iteration_id, "did": child_did, "vc_issued": True})
        except Exception:
            logger.exception("Failed to issue VC for child DID %s (iteration %s)", child_did, iteration_id)
            issued_child_vcs.append({"iterationID": iteration_id, "did": child_did, "vc_issued": False})

    response = {
        "benchmarkExecutionID": benchmarkExecutionID,
        "mode": mode,
        "master_did": parent_did,
        "iterations": result.get("iterations", []),
        "vault_path": result.get("vault_path"),
        "vc_status": {"parent_vc_issued": issued_parent_vc, "sut_vcs": issued_child_vcs},
        "correlation_id": result.get("correlation_id")
    }
    return JSONResponse(content=response)

# -------------------------
# Issue VC (kept as previous logic)
# -------------------------
@app.post("/issue-vc/{did}")
def issue_vc_for_did(did: str, token_lifespan: int = 10):
    issuer_did = ensure_issuer_did()
    # try to find mapping in did_vault by did
    rec = did_vault_col.find_one({"did": did}) or did_vault_col.find_one({"master_did": did})
    if not rec:
        # fallback: search QA collection for mapping
        rec = qa_col.find_one({"benchmarkExecutionID": {"$exists": True}, "$or": [{"resultInfo.runs.iterations.did": did}, {"resultInfo.runs.iterations.iterationID": did}]})
    if not rec:
        raise HTTPException(404, f"DID {did} not found")

    parent_id = rec.get("benchmarkExecutionID") or str(rec.get("_id"))
    vault_data = vault_fetch_secret(f"vc_tokens/{did}")
    jwt_token = vault_data.get("vc_jwt") or call_veramo_issue_vc(issuer_did, did, parent_id)
    vault_store_secret(f"vc_tokens/{did}", {"vc_jwt": jwt_token}, lifespan_minutes=token_lifespan)

    # store encrypted doc in ENCRYPTED_COLLECTION if not exists
    if not db.get_collection(ENCRYPTED_COLLECTION).find_one({"did": did}):
        # attempt to fetch parent doc for encryption (best-effort)
        parent_doc = qa_col.find_one({"benchmarkExecutionID": parent_id}) or rec
        try:
            db.get_collection(ENCRYPTED_COLLECTION).insert_one({"did": did, "encrypted_doc": encrypt_data(clean_mongo_doc(parent_doc)), "created_at": datetime.utcnow()})
        except Exception:
            logger.exception("Failed to insert encrypted doc for did %s", did)

    token = create_short_lived_token(did, jwt_token, lifespan_minutes=token_lifespan)
    return {"did": did, "token": token, "expires_in_minutes": token_lifespan}

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

# -------------------------
# Upload & Verify VC file
# -------------------------
@app.post("/vc/upload-verify")
def upload_and_verify_vc(file: UploadFile = File(...)):
    content = file.file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")

    try:
        vc_content = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {str(e)}")

    jwt_token = extract_jwt_from_vc(vc_content)
    if not jwt_token:
        raise HTTPException(400, "JWT missing in uploaded VC")

    subject_did = (
        vc_content.get("did")
        or extract_subject_did(vc_content)
        or vc_content.get("vc", {}).get("credentialSubject", {}).get("id")
    )
    if not subject_did:
        raise HTTPException(404, "Cannot determine DID from VC")

    vault_data = vault_fetch_secret(f"vc_tokens/{subject_did}")
    vault_jwt = vault_data.get("vc_jwt")
    if not vault_jwt:
        raise HTTPException(404, f"No VC entry in Vault for DID {subject_did}")
    if vault_jwt != jwt_token:
        raise HTTPException(403, f"Uploaded VC does not match stored VC for {subject_did}")

    verification_result = call_veramo_verify_vc(jwt_token)
    if not verification_result.get("verified", False):
        raise HTTPException(400, "VC verification failed")

    enc_doc = db.get_collection(ENCRYPTED_COLLECTION).find_one({"did": subject_did})
    if not enc_doc or "encrypted_doc" not in enc_doc:
        raise HTTPException(404, f"No encrypted data found for DID {subject_did}")

    decrypted_data = decrypt_data(enc_doc["encrypted_doc"])

    return {
        "did": subject_did,
        "verified": True,
        "data": decrypted_data,
        "vault_check": "VC matched with Vault and verified successfully",
        "message": "VC verified successfully. Data decrypted and accessible."
    }

# -------------------------
# Search SUT endpoint (benchmark/iteration)
# -------------------------
@app.get("/search-sut", tags=["sut"])
def search_sut(benchmarkExecutionID: Optional[str] = Query(None), iterationID: Optional[str] = Query(None), x_api_token: str = Header(...)):
    if x_api_token != API_ACCESS_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid API token")
    if not benchmarkExecutionID and not iterationID:
        raise HTTPException(status_code=400, detail="Provide benchmarkExecutionID or iterationID")

    if iterationID:
        try:
            mapping = get_from_vault_by_iteration(iterationID)
            return {"source": "vault", "mapping": mapping}
        except HTTPException:
            rec = did_vault_col.find_one({"iterationID": iterationID})
            if rec:
                return {"source": "mongo", "mapping": clean_mongo_doc(rec)}
            raise

    if benchmarkExecutionID:
        try:
            master = get_from_vault_by_benchmark(benchmarkExecutionID)
            return {"source": "vault", "mapping": master}
        except HTTPException:
            recs = list(did_vault_col.find({"benchmarkExecutionID": benchmarkExecutionID}, {"_id": 0}))
            if recs:
                return {"source": "mongo", "mappings": clean_mongo_doc(recs)}
            raise HTTPException(status_code=404, detail="No mapping found for provided benchmark/iteration")

# -------------------------
# Health
# -------------------------
@app.get("/health", tags=["health"])
def health():
    try:
        vault_ok = vault_client.is_authenticated()
    except Exception:
        vault_ok = False
    return {"status": "ok", "vault_authenticated": vault_ok, "kv_version": KV_VERSION}

# EOF
