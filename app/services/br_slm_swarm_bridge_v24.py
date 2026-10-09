"""V24 BR-only SLM shadow proposal adapter to the *existing* agent registry.

Does not create agents, assign work, import models, call tools, connect MCP,
read owner voice, or change routing. The Harness alone can authorize work.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
from typing import Any

SCHEMA = "BRSwarmSLMShadowAdmission/v24"
PROTECTED_ACTIONS = frozenset({
    "PUBLICATION", "DELIVERY", "TRAINING", "DEPLOY", "PROMOTION",
    "DEVELOPMENT", "EXECUTION", "YOUTUBE",
})
PROTECTED_TAGS = frozenset({
    "owner-voice", "voice-clone", "voice-identity", "payment",
    "billing", "credentials", "secret", "canonical-promotion",
    "publication", "security", "human-approval", "telegram-send",
})
SHADOW_ONLY = "NO_EXECUTION_SHADOW_ONLY"


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def record_role(record: Any) -> str:
    """Conservative triage; never implies model quality or tool readiness."""
    if not record.available:
        return "BLOCKED_OR_UNPROVEN"
    if not record.execution_enabled:
        return "NO_EXECUTOR"
    tags = {str(item).lower() for item in record.policy_tags}
    actions = {str(item).upper() for item in record.allowed_actions}
    if (record.side_effects or record.side_effect_class != "READ_ONLY"
            or record.capability_type in {"PROVIDER", "PRESENTATION"}
            or actions & PROTECTED_ACTIONS or tags & PROTECTED_TAGS):
        return "EXPLICIT_HARNESS_OR_HUMAN_ONLY"
    if not record.evidence_contract or not record.input_contract or not record.output_contract:
        return "CONTRACT_INCOMPLETE"
    if record.resolved_execution_kind in {
        "SEMANTIC_REASONER", "DETERMINISTIC_ANALYSIS_AGENT", "DETERMINISTIC_WORKER"
    } and record.capability_type in {"AGENT", "CAPABILITY", "EXECUTOR", "SKILL"}:
        return "SHADOW_SLM_EVALUATION_CANDIDATE"
    return "TOOL_OR_RULE_BASED_KEEP_CURRENT"


def audit_existing_swarm(registry: Any) -> dict[str, Any]:
    """Counts real Registry records, not LLM instances or live processes."""
    records = registry.all()
    if not records or len(records) > 10_000:
        raise ValueError("V24_SWARM_REGISTRY_BOUNDS")
    capabilities = [x.capability_id for x in records]
    if len(set(capabilities)) != len(capabilities):
        raise ValueError("V24_SWARM_DUPLICATE_CAPABILITY")
    rows = sorted(
        ({"capability_id": x.capability_id,
          "agent_id": x.agent_id,
          "domain": x.domain,
          "role": record_role(x),
          "executor_declared": bool(x.execution_enabled),
          "runtime_invoked": False,
          "slm_quality_validated": False,
          "slm_authority": "NONE"} for x in records),
        key=lambda x: x["capability_id"],
    )
    roles = Counter(r["role"] for r in rows)
    domains = Counter(str(r["domain"]) for r in rows)
    agents = sorted({r["agent_id"] for r in rows if r["agent_id"]})
    summary = {
        "schema_version": SCHEMA,
        "inventory_origin": "BR_GLOBAL_CAPABILITY_REGISTRY",
        "registered_capability_count": len(rows),
        "distinct_registered_agent_ids": len(agents),
        "declared_executor_capabilities": sum(x["executor_declared"] for x in rows),
        "role_counts": dict(sorted(roles.items())),
        "domain_counts": dict(sorted(domains.items())),
        "shadow_candidate_capabilities": [
            r["capability_id"] for r in rows
            if r["role"] == "SHADOW_SLM_EVALUATION_CANDIDATE"
        ],
        "not_a_runtime_probe": True,
        "not_a_model_benchmark": True,
        "model_downloaded": False,
        "agents_created": 0,
        "agents_dispatched": 0,
        "harness_routing_changed": False,
        "a15_compute": False,
        "slm_promotion_authorized": False,
    }
    summary["receipt_sha256"] = _digest(summary)
    return summary


def consider_shadow_suggestion(
    *,
    registry: Any,
    proposed_capability_id: str,
    requested_action: str,
    benchmark_approved: bool = False,
) -> dict[str, Any]:
    """Only a *non-executable* opinion. No suggestion can grant authority.

    Even with benchmark_approved, a separate Harness policy and authenticated
    task authorization are required before any executor may be used.
    """
    if not isinstance(proposed_capability_id, str) or not proposed_capability_id:
        raise ValueError("V24_SHADOW_CAPABILITY_ID_REQUIRED")
    if not isinstance(requested_action, str) or not requested_action:
        raise ValueError("V24_SHADOW_ACTION_REQUIRED")
    record = registry.get(proposed_capability_id)
    decision = "ABSTAIN"
    reason = "UNKNOWN_CAPABILITY"
    if record is not None:
        if record_role(record) != "SHADOW_SLM_EVALUATION_CANDIDATE":
            reason = "REGISTRY_POLICY_OR_READINESS_BLOCKED"
        elif requested_action.upper() not in record.allowed_actions:
            reason = "ACTION_NOT_ADMITTED_BY_HARNESS_REGISTRY"
        elif not benchmark_approved:
            reason = "INDEPENDENT_QUALITY_BENCHMARK_REQUIRED"
        else:
            decision = "PROPOSAL_ONLY"
            reason = "HARNESS_REVIEW_REQUIRED"
    result = {
        "schema_version": SCHEMA,
        "decision": decision,
        "reason": reason,
        "proposed_capability_id": proposed_capability_id,
        "requested_action": requested_action,
        "benchmark_declared_approved": benchmark_approved,
        "model_invoked": False,
        "tool_invoked": False,
        "agent_dispatched": False,
        "harness_authorization_issued": False,
        "production_promotion": False,
        "authority": SHADOW_ONLY,
    }
    result["receipt_sha256"] = _digest(result)
    return result
