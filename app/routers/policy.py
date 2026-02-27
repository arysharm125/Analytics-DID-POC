# policy_orchestrator.py
import json
import logging
from datetime import datetime
from typing import Any

from bson import json_util
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import MongoConnector
from app.routers.dependencies import get_db

# Import your DecisionEngine and MongoConnector
from app.services.decision_engine import DecisionEngine, Rule

logger = logging.getLogger("policy_orchestrator")
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/policy", tags=["policy"])

# Collections
RULES_COLL = "decision_rules"
AUDIT_COLL = "policy_decision_log"

# Pydantic models for API
class RuleIn(BaseModel):
    id: str = Field(..., description="Unique rule id")
    priority: int = Field(0, description="Higher numbers evaluated first")
    condition: str = Field(..., description="Python expression using `facts` dict")
    action: dict[str, Any] = Field(..., description="Action metadata {decision,score,...}")
    terminal: bool = Field(False, description="Stop evaluation if matched")
    description: str | None = Field("", description="Human description")

class RuleUpdate(BaseModel):
    priority: int | None
    condition: str | None
    action: dict[str, Any] | None
    terminal: bool | None
    description: str | None

class EvaluateRequest(BaseModel):
    facts: dict[str, Any]
    correlation_id: str | None = None

class EvaluateResponse(BaseModel):
    decision: str
    score: int
    matched_rules: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    explanation: str
    timestamp: str
    correlation_id: str | None

# Manager
class PolicyOrchestrator:
    def __init__(self, db: MongoConnector):
        self.db = db
        self.rules = []  # list[Rule]
        self.engine = DecisionEngine(rules=self.rules, db_connector=db, audit_collection_name=AUDIT_COLL)
        self._load_rules_from_db()

    def _load_rules_from_db(self):
        try:
            raw = list(self.db.get_collection(RULES_COLL).find({}))
            rules = []
            for r in raw:
                rid = r.get("id")
                if not rid:
                    continue
                rules.append(Rule(
                    id=rid,
                    priority=r.get("priority", 0),
                    condition=r.get("condition", ""),
                    action=r.get("action", {}),
                    terminal=r.get("terminal", False),
                    description=r.get("description", "")
                ))
            # sort and set into engine
            self.rules = sorted(rules, key=lambda x: -x.priority)
            self.engine.rules = self.rules
            logger.info("Loaded %d rules from DB", len(self.rules))
        except Exception as e:
            logger.warning("Failed to load rules from DB: %s", e)
            self.rules = []
            self.engine.rules = []

    def reload(self):
        self._load_rules_from_db()

    def list_rules(self):
        return list(self.db.get_collection(RULES_COLL).find({}, {"_id": 0}))

    def get_rule(self, rule_id: str):
        return self.db.get_collection(RULES_COLL).find_one({"id": rule_id}, {"_id": 0})

    def add_rule(self, rule_data: dict[str, Any]):
        coll = self.db.get_collection(RULES_COLL)
        existing = coll.find_one({"id": rule_data["id"]})
        if existing:
            raise HTTPException(status_code=409, detail=f"Rule {rule_data['id']} already exists")
        rule_data["created_at"] = datetime.utcnow()
        coll.insert_one(rule_data)
        self.reload()
        return rule_data

    def update_rule(self, rule_id: str, update_data: dict[str, Any]):
        coll = self.db.get_collection(RULES_COLL)
        res = coll.update_one({"id": rule_id}, {"$set": update_data})
        if res.matched_count == 0:
            raise HTTPException(status_code=404, detail="Rule not found")
        self.reload()
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: str):
        coll = self.db.get_collection(RULES_COLL)
        res = coll.delete_one({"id": rule_id})
        if res.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Rule not found")
        self.reload()
        return {"deleted": rule_id}

    def evaluate(self, facts: dict[str, Any], correlation_id: str | None = None) -> dict[str, Any]:
        return self.engine.evaluate(facts, correlation_id=correlation_id)


# Orchestrator singleton with lazy initialization using DI
_orch: PolicyOrchestrator | None = None
_orch_initialized: bool = False


def get_orchestrator(db: MongoConnector = Depends(get_db)) -> PolicyOrchestrator:
    """FastAPI dependency to get PolicyOrchestrator instance.

    Uses the get_db() dependency for database access, ensuring consistent
    initialization across all routers.
    """
    global _orch, _orch_initialized
    if not _orch_initialized:
        _orch = PolicyOrchestrator(db)
        _orch_initialized = True
    return _orch  # type: ignore


def reset_orchestrator() -> None:
    """Reset the orchestrator singleton (for testing)."""
    global _orch, _orch_initialized
    _orch = None
    _orch_initialized = False

# --- Routes ---
@router.get("/rules")
def list_rules(orchestrator: PolicyOrchestrator = Depends(get_orchestrator)):
    rows = orchestrator.list_rules()
    # ensure JSON serializable
    return json.loads(json_util.dumps(rows))

@router.get("/rules/{rule_id}")
def get_rule(rule_id: str, orchestrator: PolicyOrchestrator = Depends(get_orchestrator)):
    r = orchestrator.get_rule(rule_id)
    if not r:
        raise HTTPException(status_code=404, detail="Rule not found")
    return json.loads(json_util.dumps(r))

@router.post("/rules", status_code=201)
def create_rule(r: RuleIn, orchestrator: PolicyOrchestrator = Depends(get_orchestrator)):
    data = r.dict()
    # Basic validation: Try a dry-run safe eval of condition using empty facts
    try:
        # attempt to evaluate as boolean with empty facts to find syntax errors
        from app.services.decision_engine import safe_eval
        safe_eval(data["condition"], facts={})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid condition expression: {e}")
    created = orchestrator.add_rule(data)
    return json.loads(json_util.dumps(created))

@router.put("/rules/{rule_id}")
def put_rule(rule_id: str, update: RuleUpdate = Body(...), orchestrator: PolicyOrchestrator = Depends(get_orchestrator)):
    data = {k:v for k,v in update.dict().items() if v is not None}
    updated = orchestrator.update_rule(rule_id, data)
    return json.loads(json_util.dumps(updated))

@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, orchestrator: PolicyOrchestrator = Depends(get_orchestrator)):
    return orchestrator.delete_rule(rule_id)

@router.post("/reload")
def reload_rules(orchestrator: PolicyOrchestrator = Depends(get_orchestrator)):
    orchestrator.reload()
    return {"status": "reloaded", "rules_loaded": len(orchestrator.rules)}

@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate(req: EvaluateRequest, orchestrator: PolicyOrchestrator = Depends(get_orchestrator)):
    facts = req.facts
    corr = req.correlation_id
    # evaluate via engine
    result = orchestrator.evaluate(facts, correlation_id=corr)
    # result is already JSON-safe (engine used json_util)
    return result
