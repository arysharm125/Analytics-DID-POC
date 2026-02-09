# app/routers/audit.py
from fastapi import APIRouter, HTTPException, status, Path
from pydantic import BaseModel, Field
from celery.result import AsyncResult
from typing import Optional, Dict, Any
import os
import requests
import logging

# Import the celery app to send tasks
from app.celery_worker import celery_app
from app.services.scoring import validate_and_score_benchmark_data

router = APIRouter(tags=["Analytics & Audit"])
logger = logging.getLogger("audit_api")

# Config
EPDW_API_URL = os.getenv("EPDW_API_URL", "http://epdw.dev.amd.com:8001/public/getBenchmarkResult")
EPDW_TOKEN = os.getenv("EPDW_TOKEN")

# Models
class AuditRequest(BaseModel):
    host: str = Field(..., example="10.86.27.69")
    username: str = Field(..., example="amd")
    password: str = Field(..., example="amd123")
    benchmark_name: str = Field(..., example="SPECCPU")

class TaskResponse(BaseModel):
    task_id: str
    status: str

@router.post("/pre_flight_analytics", response_model=TaskResponse, status_code=202)
async def start_audit(request: AuditRequest):
    """Trigger the dynamic audit engine via Celery."""
    try:
        # Use send_task to invoke the task registered in worker
        task = celery_app.send_task(
            "audit.run_audit_task",
            args=[request.host, request.username, request.password, request.benchmark_name]
        )
        return {"task_id": task.id, "status": "QUEUED"}
    except Exception as e:
        logger.error(f"Queue failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/result/{task_id}")
async def get_audit_result(task_id: str):
    res = AsyncResult(task_id, app=celery_app)
    if res.state == 'FAILURE':
        return {"task_id": task_id, "status": "FAILURE", "error": str(res.info)}
    return {"task_id": task_id, "status": res.state, "result": res.result if res.ready() else None}

@router.post("/post_flight_check/{benchmark_execution_id}")
async def post_flight_check(benchmark_execution_id: str):
    headers = {"accept": "application/json"}

    # OPTIONAL token logic
    if EPDW_TOKEN:
        headers["Authorization"] = f"Bearer {EPDW_TOKEN}"
    else:
        logger.warning("EPDW_TOKEN not set, calling EPDW API without auth")

    try:
        resp = requests.get(
            EPDW_API_URL,
            headers=headers,
            params={"benchmarkExecutionID": benchmark_execution_id},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()

        passed, msg, score, details = validate_and_score_benchmark_data(data)

        return {
            "benchmark_execution_id": benchmark_execution_id,
            "status": "PASS" if passed else "FAIL",
            "compliance_score": score,
            "message": msg,
            "details": details
        }

    except Exception as e:
        logger.error(f"Post-flight check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

#@router.post("/post_flight_check/{benchmark_execution_id}")
#async def post_flight_check(benchmark_execution_id: str):
#    if not EPDW_TOKEN:
#        raise HTTPException(500, "EPDW_TOKEN not configured")
#    
#    headers = {"accept": "application/json", "Authorization": f"Bearer {EPDW_TOKEN}"}
#    try:
#        resp = requests.get(
#            EPDW_API_URL, 
#            headers=headers, 
#            params={"benchmarkExecutionID": benchmark_execution_id},
#            timeout=30
#        )
#        resp.raise_for_status()
#        data = resp.json()
#        
#        # Use the logic from your provided code
#        passed, msg, score, details = validate_and_score_benchmark_data(data)
#        
#        return {
#            "benchmark_execution_id": benchmark_execution_id,
#            "status": "PASS" if passed else "FAIL",
#            "compliance_score": score,
#            "message": msg,
#            "details": details
#        }
#    except Exception as e:
#        logger.error(f"Post-flight check failed: {e}")
#        raise HTTPException(500, detail=str(e))
