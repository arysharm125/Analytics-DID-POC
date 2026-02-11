# app/tasks.py
import time

# Celery Imports
from celery.signals import worker_process_init
from celery.utils.log import get_task_logger

# App Imports
from app.celery_worker import celery_app

# Service Imports
from app.services.audit_core import ServerAuditEngine

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

@celery_app.task(bind=True, name="audit.run_direct_network_audit")
def run_direct_network_audit_task(self, host: str, username: str, password: str):
    """
    Executes ONLY the network audit via SSH, bypassing API checks.
    """
    if auditor is None:
        raise RuntimeError("Auditor failed to initialize. Check worker startup logs.")

    try:
        logger.info(f"Starting DIRECT audit task {self.request.id} for {host}")
        start_time = time.time()

        report = auditor.run_direct_network_audit(
            host=host,
            user=username,
            password=password
        )

        duration = round(time.time() - start_time, 2)
        report['task_id'] = self.request.id
        report['duration_seconds'] = duration

        logger.info(f"Direct audit task {self.request.id} completed in {duration}s")
        return report

    except Exception as e:
        logger.error(f"Direct audit task failed for {host}: {e}")
        raise e
