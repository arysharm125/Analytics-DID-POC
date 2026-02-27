# decision_engine.py
import json
import logging
import time
from datetime import datetime
from typing import Any

from bson import ObjectId, json_util

logger = logging.getLogger("decision_engine")
logger.setLevel(logging.INFO)

# ---------- Safe eval helpers ----------
SAFE_GLOBALS = {"__builtins__": {}}
SAFE_LOCALS_ALLOWED = {
    "len": len,
    "min": min,
    "max": max,
    "all": all,
    "any": any,
    "sum": sum,
}

def safe_eval(expr: str, facts: dict) -> bool:
    """
    Evaluate a condition expression safely with limited globals.
    The expression should reference `facts`, e.g. facts['vc_verified'] == True
    """
    local_vars = {"facts": facts}
    local_vars.update(SAFE_LOCALS_ALLOWED)
    try:
        return bool(eval(expr, SAFE_GLOBALS, local_vars))
    except Exception as e:
        logger.debug("safe_eval error for '%s': %s", expr, e)
        return False

# ---------- Rule dataclass ----------
class Rule:
    def __init__(self, id: str, priority: int, condition: str, action: dict, terminal: bool=False, description: str=""):
        self.id = id
        self.priority = int(priority)
        self.condition = condition
        self.action = action
        self.terminal = bool(terminal)
        self.description = description

    def matches(self, facts: dict[str, Any]) -> bool:
        return safe_eval(self.condition, facts)

# ---------- Decision Engine ----------
class DecisionEngine:
    def __init__(self, rules: list[Rule] | None = None, db_connector = None, audit_collection_name: str = "did_audit_log"):
        """
        rules: list of Rule objects (if None, start empty)
        db_connector: optional MongoConnector instance for auditing
        """
        self.rules = sorted(rules or [], key=lambda r: -r.priority)
        self.db = db_connector
        self.audit_collection_name = audit_collection_name

    def load_rules_from_json(self, json_path: str):
        with open(json_path) as fh:
            payload = json.load(fh)
        rules = []
        for r in payload.get("rules", []):
            rules.append(Rule(
                id=r["id"], priority=r.get("priority", 0),
                condition=r["condition"], action=r["action"],
                terminal=r.get("terminal", False), description=r.get("description", "")
            ))
        self.rules = sorted(rules, key=lambda r: -r.priority)

    def evaluate(self, facts: dict[str, Any], correlation_id: str | None = None) -> dict[str, Any]:
        """
        Evaluate rules against facts. Returns dict:
        {
          "decision": "allow"/"deny"/"review"/"none",
          "score": 12,
          "matched_rules": [...],
          "actions": [...],
          "explanation": "...",
          "timestamp": "...",
          "correlation_id": "...",
        }
        """
        time.time()
        facts_clean = self._sanitize_facts(facts)
        matched_rules = []
        actions = []
        score = 0
        decision = "none"

        for rule in self.rules:
            try:
                if rule.matches(facts_clean):
                    matched_rules.append({"id": rule.id, "priority": rule.priority, "action": rule.action, "description": rule.description})
                    actions.append(rule.action)
                    score += int(rule.action.get("score", 0))
                    # rule action may include decision override
                    if "decision" in rule.action:
                        decision = rule.action["decision"]
                    if rule.terminal:
                        break
            except Exception as e:
                logger.exception("Rule eval error for %s: %s", rule.id, e)

        # fallback: if no matching decision set default deny/none
        if decision == "none":
            # simple threshold policy: if score > 0 => allow
            decision = "allow" if score > 0 else "deny"

        result = {
            "decision": decision,
            "score": score,
            "matched_rules": matched_rules,
            "actions": actions,
            "explanation": f"{len(matched_rules)} rules matched, score={score}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "correlation_id": correlation_id
        }

        # audit persist (best-effort)
        self._audit(facts, result)

        logger.info("DecisionEngine evaluate: decision=%s score=%s matched=%s", decision, score, [r["id"] for r in matched_rules])
        logger.debug("Decision details: %s", result)
        return result

    def _sanitize_facts(self, facts: dict[str, Any]) -> dict[str, Any]:
        # Convert ObjectId and other BSON -> string for safe eval and readability
        def conv(v):
            if isinstance(v, ObjectId):
                return str(v)
            if isinstance(v, dict):
                return {k: conv(vv) for k, vv in v.items()}
            if isinstance(v, list):
                return [conv(i) for i in v]
            return v
        return conv(facts)

    def _audit(self, facts: dict[str, Any], result: dict[str, Any]):
        if not self.db:
            return
        try:
            rec = {
                "facts": json.loads(json_util.dumps(facts)),
                "result": json.loads(json_util.dumps(result)),
                "created_at": datetime.utcnow()
            }
            coll = self.db.get_collection(self.audit_collection_name)
            coll.insert_one(rec)
        except Exception as e:
            logger.warning("Failed to write audit record: %s", e)

# ---------- Example default rules ----------
default_rules_example = [
    Rule(
        id="r_vc_valid_allow",
        priority=200,
        condition="facts.get('vc_verified') == True and facts.get('entitlement', {}).get('level') in ('L2','L3')",
        action={"decision":"allow","score":50,"note":"VC verified & entitlement L2/L3"},
        terminal=True,
        description="Strong allow when VC verification succeeded and entitlement good"
    ),
    Rule(
        id="r_no_vc_deny",
        priority=10,
        condition="not facts.get('vc_verified')",
        action={"decision":"deny","score":-100,"note":"No valid VC"},
        terminal=True,
        description="Deny if VC not valid"
    ),
    Rule(
        id="r_low_level_review",
        priority=50,
        condition="facts.get('entitlement',{}).get('level') == 'L1'",
        action={"decision":"review","score":5,"note":"L1 requires manual review"},
        terminal=False,
        description="Flag L1 for review"
    ),
    Rule(
        id="r_revoked_vc_deny",
        priority=300,
        condition="facts.get('vc_revoked') == True",
        action={"decision":"deny","score":-100,"note":"VC revoked"},
        terminal=True,
        description="Reject if token is revoked"
    )
]

# ---------- Simple self-test ----------
if __name__ == "__main__":
    engine = DecisionEngine(rules=default_rules_example)
    facts = {
        "vc_verified": True,
        "vc_revoked": False,
        "entitlement": {"level": "L2", "access": "read-only"},
        "benchmarkExecutionID": "B001",
        "iterationID": "iter-002"
    }
    print(json.dumps(engine.evaluate(facts), indent=2))

