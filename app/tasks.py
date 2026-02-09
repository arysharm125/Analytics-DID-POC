# app/tasks.py
import uuid
import time
import logging
from datetime import datetime
from bson import ObjectId
from pymongo.errors import OperationFailure

# Celery Imports
from celery.signals import worker_process_init
from celery.utils.log import get_task_logger

# App Imports
from app.constants import COLLECTION_NAME, ENCRYPTED_COLLECTION
from app.celery_worker import celery_app
from app.database import MongoConnector

# Service Imports
from app.services.audit_core import ServerAuditEngine

# Utility Imports
from app.utils import (
    call_veramo_create_did, 
    get_or_create_issuer_did,
    call_veramo_issue_vc,
    vault_store_secret, 
    encrypt_data, 
    clean_for_json,
    create_short_lived_token, 
    init_vault_client
)

logger = get_task_logger(__name__)

# ==========================================
# 1. AUDIT ENGINE INITIALIZATION (Worker)
# ==========================================
# Global instance for the worker process
auditor = None

@worker_process_init.connect
def init_auditor(**kwargs):
    """
    Initialize ServerAuditEngine when a Celery worker process starts.
    This ensures we load the JSON tuning maps only once per worker, 
    not per request.
    """
    global auditor
    try:
        auditor = ServerAuditEngine()
        logger.info("ServerAuditEngine initialized successfully in worker.")
    except Exception as e:
        logger.error(f"FATAL: Failed to initialize ServerAuditEngine: {e}")
        auditor = None

# ==========================================
# 2. AUDIT TASKS
# ==========================================
@celery_app.task(bind=True, name="audit.run_audit_task")
def run_audit_task(self, host: str, username: str, password: str, benchmark_name: str):
    """
    Executes the full server audit (Pre-Flight) logic.
    """
    if auditor is None:
        raise RuntimeError("Auditor failed to initialize. Check worker startup logs.")

    try:
        logger.info(f"Starting audit task {self.request.id} for {host}")
        start_time = time.time()

        # Run the logic defined in app/services/audit_core.py
        report = auditor.run_full_audit(
            host=host,
            username=username,
            password=password,
            benchmark_name=benchmark_name
        )

        duration = round(time.time() - start_time, 2)
        report['task_id'] = self.request.id
        report['duration_seconds'] = duration
        
        logger.info(f"Audit task {self.request.id} completed in {duration}s")
        return report

    except Exception as e:
        logger.error(f"Audit task failed for {host}: {e}")
        # Re-raise to ensure Celery marks the task state as FAILURE
        raise e

# ==========================================
# 3. DID GENERATION TASKS
# ==========================================
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
    It writes its final result into MongoDB (`did_vault` collection).
    """
    print(f"[TASK] Starting DID generation for record: {record_id_str}")
    db_update_status = "pending"
    did = alias = token = None
    token_lifespan = 10  # minutes

    try:
        # A. Initialise clients (inside the worker)
        db = MongoConnector()
        init_vault_client()

        object_id = ObjectId(record_id_str)
        # Assuming the caller guarantees the record exists, but good to check:
        # We need to know WHICH collection to query. 
        # Standard flow implies looking at QA_COLLECTION or similar.
        # For generic usage, we usually assume the 'qa_benchmark_executions' or similar.
        # However, purely based on the original snippet, we need 'record'. 
        # Let's fetch it from the generic 'qa_benchmark_executions' for context
        # or assume it's passed. 
        # NOTE: The original code had `if not record: raise ValueError`. 
        # We must fetch it first.
        
        qa_col = db.get_collection(COLLECTION_NAME) # Using imported constant
        record = qa_col.find_one({"_id": object_id})
        
        if not record:
            raise ValueError(f"Record {record_id_str} not found in {COLLECTION_NAME}")

        parent_id = str(record["_id"])

        # B. DID creation / reuse
        if not record.get("did"):
            alias = f"{amd_alias_prefix}-{parent_id}-{uuid.uuid4().hex[:6]}"
            veramo_resp = call_veramo_create_did(alias)
            did = veramo_resp["did"]
            print(f"[TASK] DID created: {did}")

            # try to write DID back to the original collection
            try:
                upd = qa_col.update_one(
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

        # C. Issue VC & store in Vault
        issuer_did = get_or_create_issuer_did()
        jwt = call_veramo_issue_vc(issuer_did, did, parent_id)
        vault_store_secret(f"vc_tokens/{did}", {"vc_jwt": jwt}, lifespan_minutes=10)

        # D. Encrypt original document (once)
        enc_col = db.get_collection(ENCRYPTED_COLLECTION)
        if not enc_col.find_one({"did": did}):
            cleaned = clean_for_json(record)
            if "_id" not in cleaned:
                cleaned["_id"] = str(object_id)
            encrypted = encrypt_data(cleaned)
            enc_col.insert_one(
                {"did": did, "encrypted_doc": encrypted, "created_at": datetime.utcnow()}
            )

        # E. Short-lived access token
        token = create_short_lived_token(did, jwt, lifespan_minutes=token_lifespan)

        # F. Final status
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

        # Persist result for polling
        db.get_collection("did_vault").update_one(
            {"task_id": self.request.id},
            {"$set": {"result": result, "finished_at": datetime.utcnow()}},
            upsert=True,
        )

        return result

    except Exception as exc:
        if self.request.retries < self.max_retries:
            logger.warning("Retrying task %s (retry %s): %s", self.request.id, self.request.retries, exc)
            raise exc
        else:
            logger.error("Permanent failure for task %s: %s", self.request.id, exc)
            # We need 'db' to write failure, check if initialized
            try:
                if 'db' not in locals(): db = MongoConnector()
                
                fail_result = {
                    "status": "failure",
                    "record_id": record_id_str,
                    "db_update_status": locals().get('db_update_status', 'unknown'),
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
            except Exception as final_e:
                logger.error(f"Failed to write failure log to DB: {final_e}")
                raise exc