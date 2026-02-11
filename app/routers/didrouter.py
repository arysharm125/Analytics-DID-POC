from fastapi import HTTPException, UploadFile, File, Query, Header, APIRouter
from fastapi.responses import StreamingResponse, JSONResponse
from datetime import datetime
import json
import logging
from app.utils import generate_did
from typing import List, Optional, Any, Dict
from pydantic import BaseModel
import io
from app.utils import  merkle_root
import pymongo
from bson import json_util

#  Import constants (environment configs, collection names)
from app.constants import (
    VAULT_MOUNT,
    API_ACCESS_TOKEN,
    VC_TOKEN_COLLECTION,
)

from app.services.vault import (
    vault_store_secret,
    vault_list,
    vault_read_dict,
    vault_is_authenticated,
)

# 🔹 Import utility functions from app.utils.py
from app.utils import (
    now_iso,
    vault_write,
    vault_read,
    ensure_issuer_did,
    call_veramo_issue_vc,
    call_veramo_verify_vc,
    extract_jwt_from_vc,
    extract_subject_did,
    create_short_lived_token,
    vault_fetch_secret,
    decrypt_data,
    get_from_vault_by_did,
    create_and_store_mappings,
    normalize_vault_object,
    compute_diff,
    now_timestamp,
    apply_global_updates,
    get_vault_stored_vc_for_did,
    is_issuer_allowed,

    # DB (initialized automatically in utils.py)
    db,
    qa_col,
    did_vault_col,
    audit_log,
)


# ==========================
# Logging
# ==========================
logger = logging.getLogger("did_vault_api_sut")
logger.setLevel(logging.INFO)


app = APIRouter()

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


async def startup_did_router():
        # init vault client and issuer
    try:
        if vault_is_authenticated():
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
            from app.utils import get_encrypted_payload_from_vault, decrypt_data
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
from app.utils import validate_amd_email

def deep_merge(old: dict, new: dict) -> dict:
    merged = old.copy()
    for key, value in new.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@app.post("/append-did", tags=["sut"])
async def append_did(
    body: DIDAppendRequest,
    update_message: str = Query(...),
    updated_by: str = Query(...)
):
    validate_amd_email(updated_by)

    benchmarkExecutionID = body.benchmarkExecutionID
    iterationID = body.iterationID
    incoming_data = body.data or {}

    if not benchmarkExecutionID or not iterationID:
        raise HTTPException(400, "benchmarkExecutionID and iterationID are required")

    # =========================
    # 🚫 BLOCKED KEYS CHECK (ADDED HERE)
    # =========================
    BLOCKED_KEYS = {"_id", "did", "benchmarkExecutionID", "iterationID"}

    for key in incoming_data:
        if key in BLOCKED_KEYS:
            raise HTTPException(
                status_code=400,
                detail=f"Updates not allowed for key: {key}"
            )

    # =========================
    # 🔍 FETCH TARGET RECORD
    # =========================
    record = did_vault_col.find_one({
        "benchmarkExecutionID": benchmarkExecutionID,
        "iterationID": iterationID
    })

    if not record:
        raise HTTPException(404, "Record not found in did_vault")

    old_did = record["did"]
    old_data = record.get("data") or {}
    is_master = record.get("is_master", False)

    # =========================
    # 🧠 AUTHORITATIVE UPDATE
    # =========================
    new_data = apply_global_updates(old_data, incoming_data)
    diff_log = compute_diff(old_data, new_data)

    # Reject no-op updates
    if not any(diff_log.values()):
        raise HTTPException(400, "No changes detected in payload")

    new_did = generate_did(None)

    # =========================
    # 🔗 VAULT CHAIN HANDLING
    # =========================
    folder = "master" if is_master else iterationID
    chain_path = f"{folder}/chain"

    try:
        chain_raw = vault_read(VAULT_MOUNT, chain_path)
    except Exception:
        chain_raw = None

    chain_list = (
        chain_raw.get("chain", [])
        if isinstance(chain_raw, dict)
        else chain_raw
        if isinstance(chain_raw, list)
        else []
    )

    chain_list.append(new_did)
    merkle = merkle_root(chain_list)

    vault_write(VAULT_MOUNT, chain_path, {"chain": chain_list})

    # =========================
    # 🗄️ VAULT SNAPSHOT
    # =========================
    snapshot = {
        "did": new_did,
        "previous_did": old_did,
        "timestamp": now_timestamp(),
        "benchmarkExecutionID": benchmarkExecutionID,
        "iterationID": iterationID,
        "data": new_data,
        "previous_data": old_data,
        "diff": diff_log,
        "updated_by": updated_by,
        "update_message": update_message,
        "merkle_root": merkle
    }

    vault_write(
        VAULT_MOUNT,
        f"{folder}/{new_did}",
        {"data": snapshot}
    )

    # =========================
    # 🧾 UPDATE MONGO
    # =========================
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
                "update_message": update_message,
                "is_master": is_master,
                "diff": diff_log
            }
        }
    )

    # =========================
    # ✅ RESPONSE
    # =========================
    return {
        "status": "updated",
        "benchmarkExecutionID": benchmarkExecutionID,
        "iterationID": iterationID,
        "did": new_did,
        "previous_did": old_did,
        "chain_length": len(chain_list),
        "diff": diff_log,
        "message": "DID updated with authoritative deep JSON overwrite"
    }

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


@app.get("/did-history", tags=["sut"])
def get_did_history(
    benchmarkExecutionID: str = Query(...),
    iterationID: Optional[str] = Query(None)
):
    """
    DID Version History (Read-Only)

    Returns complete version lineage with:
    ✓ DID Chain (Merkle protected)
    ✓ Full snapshots from Vault
    ✓ Diff logs (audit)
    ✓ Who updated + Why
    ✓ When updated
    """

    # 1️⃣ Identify correct record from did_vault
    if not iterationID:
        records = list(did_vault_col.find({"benchmarkExecutionID": benchmarkExecutionID}))
        if not records:
            raise HTTPException(404, "No matching benchmarkExecutionID found")
        iter_ids = list({r.get("iterationID") for r in records if r.get("iterationID")})
        if len(iter_ids) != 1:
            raise HTTPException(400, "Specify iterationID explicitly")
        iterationID = iter_ids[0]

    record = did_vault_col.find_one({
        "benchmarkExecutionID": benchmarkExecutionID,
        "iterationID": iterationID
    })

    if not record:
        raise HTTPException(404, f"No record for {benchmarkExecutionID}/{iterationID}")

    current_did = record.get("did")
    seen = set()
    chain = []
    did = current_did

    # 2️⃣ Walk DID chain using previous_did reference
    while did and did not in seen:
        seen.add(did)
        chain.append(did)
        try:
            data = vault_read_dict(mount_point="secret", path=f"{iterationID}/{did}")
            did = data.get("previous_did")
        except Exception:
            break

    # 3️⃣ Fallback — include any orphan snapshots in Vault
    try:
        extra_dids = vault_list(mount_point="secret", path=iterationID)
        chain = list(dict.fromkeys(chain + extra_dids))
    except Exception:
        pass

    # 4️⃣ Retrieve ALL snapshots from Vault (READ ONLY)
    history = []
    for did in chain:
        try:
            data = vault_read_dict(mount_point="secret", path=f"{iterationID}/{did}")

            history.append({
                "did": did,
                "timestamp": data.get("timestamp"),
                "data": data.get("data"),  # full updated JSON
                "previous_data": data.get("previous_data"),  # 👈 full old JSON
                "diff": data.get("diff"),  # 👈 what changed
                "updated_by": data.get("updated_by"),
                "update_message": data.get("update_message"),
                "previous_did": data.get("previous_did"),
                "merkle_root": data.get("merkle_root"),
                "iterationID": iterationID,
                "benchmarkExecutionID": benchmarkExecutionID
            })
        except Exception:
            history.append({"did": did, "error": "missing or unreadable"})

    # 5️⃣ Sort by actual version timestamp
    history_sorted = sorted(history, key=lambda h: h.get("timestamp") or "")

    # Find current snapshot for diff + audit details
    current_snapshot = next((h for h in history_sorted if h.get("did") == current_did), None)

    return {
        "benchmarkExecutionID": benchmarkExecutionID,
        "iterationID": iterationID,
        "chain": [h["did"] for h in history_sorted],
        "versions": history_sorted,
        "total_versions": len(history_sorted),
        "current": {
            "did": current_did,
            "data": record.get("data"),
            "merkle_root": record.get("merkle_root"),
            "last_updated": record.get("last_updated"),
            "updated_by": record.get("updated_by"),
            "update_message": record.get("update_message"),
            "diff": current_snapshot.get("diff") if current_snapshot else None,
            "previous_did": current_snapshot.get("previous_did") if current_snapshot else None
        }
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
        keys = vault_list(mount_point="secret", path=iterationID)

        did_records = []

        for key in keys:
            if key.endswith("/"):  # Skip inner folders if any
                continue

            data = vault_read_dict(mount_point="secret", path=f"{iterationID}/{key}")
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
