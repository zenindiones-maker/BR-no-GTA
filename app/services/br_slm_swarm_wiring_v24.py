"""Inspect existing BR Harness ⇄ Agent Office ⇄ Hermes metadata wiring.

No task dispatch, model inference, mutation, permission grant, or new agent.
Checks exact declared contracts; live executor readiness is NOT inferred.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


def reconcile_existing_wiring(*, registry: Any, office_profiles: Any, hermes_roster: Any) -> dict:
    records = registry.all()
    if not records or len(records) > 10_000:
        raise ValueError("V24_WIRING_REGISTRY_BOUNDS")
    by_capability = {r.capability_id: r for r in records}
    if len(by_capability) != len(records):
        raise ValueError("V24_WIRING_DUPLICATE_CAPABILITY")
    expected_agent_caps = {
        r.capability_id for r in records if r.agent_id and r.execution_enabled
    }
    expected_executor_caps = {
        r.capability_id for r in records
        if r.execution_enabled and r.executor_binding and r.evidence_contract
    }
    office_by_id = {}
    for p in office_profiles:
        if p.capability_id in office_by_id:
            raise ValueError("V24_WIRING_DUPLICATE_OFFICE_PROFILE")
        office_by_id[p.capability_id] = p
    hermes_by_id = {}
    for h in hermes_roster:
        if h.capability_id in hermes_by_id:
            raise ValueError("V24_WIRING_DUPLICATE_HERMES_PROJECTION")
        hermes_by_id[h.capability_id] = h
    errors = []
    for capability_id in sorted(expected_agent_caps):
        p = office_by_id.get(capability_id)
        r = by_capability[capability_id]
        if (p is None or p.agent_id != r.agent_id or p.capability_id != capability_id
                or p.authority != "DELEGATED_ONLY"
                or not p.tools or p.tools[0] != r.executor_binding
                or tuple(p.allowed_actions) != tuple(r.allowed_actions)
                or p.evidence_contract != r.evidence_contract):
            errors.append("AGENT_OFFICE_PROFILE_DRIFT:" + capability_id)
    for capability_id in sorted(expected_executor_caps):
        h = hermes_by_id.get(capability_id)
        r = by_capability[capability_id]
        if (h is None or h.executor_binding != r.executor_binding
                or h.agent_id != r.agent_id or h.skill_id != r.skill_id
                or tuple(h.allowed_actions) != tuple(r.allowed_actions)
                or h.evidence_contract != r.evidence_contract
                or h.security_boundary != r.security_boundary):
            errors.append("HERMES_DECLARED_CONTRACT_DRIFT:" + capability_id)
    for cid in office_by_id.keys() - expected_agent_caps:
        errors.append("EXTRA_OFFICE_PROFILE:" + cid)
    for cid in hermes_by_id.keys() - expected_executor_caps:
        errors.append("EXTRA_HERMES_PROJECTION:" + cid)
    result = {
        "schema_version": "BRSwarmDeclaredWiringAudit/v24",
        "registry_capabilities": len(records),
        "expected_agent_profiles": len(expected_agent_caps),
        "agent_office_profile_count": len(office_by_id),
        "expected_hermes_executors": len(expected_executor_caps),
        "hermes_projection_count": len(hermes_by_id),
        "metadata_wiring_status": "PASS" if not errors else "FAIL",
        "anomalies": sorted(errors),
        "runtime_executor_calls": 0,
        "real_agent_sessions_proven": False,
        "slm_inference_executed": False,
        "harness_authority_changed": False,
        "agent_creation": False,
    }
    result["receipt_sha256"] = sha256(json.dumps(
        result, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()).hexdigest()
    return result
