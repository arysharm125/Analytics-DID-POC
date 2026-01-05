from constants import COLLECTION_NAME
# tasks.py
import uuid
from datetime import datetime
from bson import ObjectId
import logging
from pymongo.errors import OperationFailure

from app.celery_worker import celery_app
from app.database import MongoConnector

# All helpers are now in utils.py (same as the API)
from app.utils import (
    call_veramo_create_did, get_or_create_issuer_did,
    call_veramo_issue_vc,
    vault_store_secret, encrypt_data, clean_for_json,
    create_short_lived_token, init_vault_client
)

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_did_generation_task(
    self,
    record_id_str: str,
    amd_alias_prefix: str = "amd",
    benchmark_execution_id: str | None = None,
    iteration_id: str | None = None,
) -> dict:
    """
    Celery task that mirrors the old logic but works with the new API utils.
    It is **started from the FastAPI endpoint** (see below) and writes its
    final result into MongoDB (`did_vault` collection) for easy polling.

    Returns
    -------
    dict
        {
            "status": "success|partial_success|failure",
            "record_id": str,
            "did": str,
            "did_alias": str|None,
            "token": str|None,
            "expires_in_minutes": int,
            "db_update_status": str,
            "message": str,
            "benchmarkExecutionID": str|None,
            "iterationID": str|None,
        }
    """
    print(f"[TASK] Starting DID generation for record: {record_id_str}")
    db_update_status = "pending"
    did = alias = token = None
    token_lifespan = 10  # minutes

    try:
        # ------------------------------------------------------------------
        # 1. Initialise clients (inside the worker – no pickling issues)
        # ------------------------------------------------------------------
        db = MongoConnector()
        init_vault_client()

        object_id = ObjectId(record_id_str)
        if not record:
            raise ValueError("Record not found")

        parent_id = str(record["_id"])

        # ------------------------------------------------------------------
        # 2. DID creation / reuse
        # ------------------------------------------------------------------
        if not record.get("did"):
            alias = f"{amd_alias_prefix}-{parent_id}-{uuid.uuid4().hex[:6]}"
            veramo_resp = call_veramo_create_did(alias)
            did = veramo_resp["did"]
            print(f"[TASK] DID created: {did}")

            # ---- try to write DID back to the original collection ----
            try:
                upd = db.update_doc(
                    {"_id": object_id},
                    {"$set": {"did": did, "did_alias": alias}},
                )
                db_update_status = "success" if upd.modified_count else "not_modified"
            except OperationFailure as op_err:
                if op_err.code == 13:  # Unauthorized (read-only)
                    db_update_status = "failed_unauthorized"
                    print(f"[TASK-WARN] Read-only DB – DID not saved: {did}")
                else:
                    raise
        else:
            did = record["did"]
            alias = record.get("did_alias", "")
            db_update_status = "already_exists"
            print(f"[TASK] Re-using existing DID: {did}")

        if not did:
            raise ValueError("DID missing after creation step")

        # ------------------------------------------------------------------
        # 3. Issue VC & store in Vault
        # ------------------------------------------------------------------
        issuer_did = get_or_create_issuer_did()
        jwt = call_veramo_issue_vc(issuer_did, did, parent_id)
        vault_store_secret(f"vc_tokens/{did}", {"vc_jwt": jwt}, lifespan_minutes=10)

        # ------------------------------------------------------------------
        # 4. Encrypt original document (once)
        # ------------------------------------------------------------------
        if not db.get_collection(ENCRYPTED_COLLECTION).find_one({"did": did}):
            cleaned = clean_for_json(record)
            if "_id" not in cleaned:
                cleaned["_id"] = str(object_id)
            encrypted = encrypt_data(cleaned)
            db.get_collection(ENCRYPTED_COLLECTION).insert_one(
                {"did": did, "encrypted_doc": encrypted, "created_at": datetime.utcnow()}
            )

        # ------------------------------------------------------------------
        # 5. Short-lived access token
        # ------------------------------------------------------------------
        token = create_short_lived_token(did, jwt, lifespan_minutes=token_lifespan)

        # ------------------------------------------------------------------
        # 6. Final status
        # ------------------------------------------------------------------
        success = (
            "success"
            if db_update_status in ("success", "already_exists", "not_modified")
            else "partial_success"
        )
        msg = "DID/VC processed successfully."
        if db_update_status == "failed_unauthorized":
            msg = "DID/VC processed, but DID could not be saved (read-only DB)."

        result = {
            "status": success,
            "record_id": parent_id,
            "did": did,
            "did_alias": alias,
            "token": token,
            "expires_in_minutes": token_lifespan,
            "db_update_status": db_update_status,
            "message": msg,
            "benchmarkExecutionID": benchmark_execution_id,
            "iterationID": iteration_id,
        }

        # Persist result for polling (optional but handy)
        db.get_collection("did_vault").update_one(
            {"task_id": self.request.id},
            {"$set": {"result": result, "finished_at": datetime.utcnow()}},
            upsert=True,
        )

        return result

    except Exception as exc:
        # ------------------------------------------------------------------
        # Retry logic – Celery will honour max_retries
        # ------------------------------------------------------------------
        if self.request.retries < self.max_retries:
            logger.warning("Retrying task %s (retry %s): %s", self.request.id, self.request.retries, exc)
            raise exc  # triggers Celery retry
        else:
            logger.error("Permanent failure for task %s: %s", self.request.id, exc)
            fail_result = {
                "status": "failure",
                "record_id": record_id_str,
                "db_update_status": db_update_status,
                "message": f"Task failed after retries: {exc}",
                "benchmarkExecutionID": benchmark_execution_id,
                "iterationID": iteration_id,
            }
            db.get_collection("did_vault").update_one(
                {"task_id": self.request.id},
                {"$set": {"result": fail_result, "finished_at": datetime.utcnow()}},
                upsert=True,
            )
            return fail_result
