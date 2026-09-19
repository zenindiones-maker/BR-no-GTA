from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.gta6_brain import GTA6Brain
from app.services.harness_ai_provider_service import select_harness_ai_provider
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    consume_harness_authorization,
    issue_harness_authorization,
    resolve_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_episode_capture_service import capture_canonical_execution_episode
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.swarm_execution_proof_service import AgentInvocationReceipt


GTA6_BRAIN_CAPABILITY_ID = "gta6.brain.decide"
GTA6_BRAIN_EXECUTOR_BINDING = (
    "app.services.gta6_brain_harness_service.execute_authorized_gta6_brain_decision"
)


def execute_authorized_gta6_brain_decision(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> CapabilityEvidence:
    """Execute one GTA6 domain decision without granting execution authority."""
    auth = resolve_harness_authorization(authorization)
    auth = validate_harness_authorization(
        auth,
        expected_action="DECISION",
        expected_subject=f"capability:{GTA6_BRAIN_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(GTA6_BRAIN_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("gta6.brain.decide is not executable")
    if record.executor_binding != GTA6_BRAIN_EXECUTOR_BINDING:
        raise PermissionError("gta6.brain.decide Registry executor mismatch")
    if routing_decision.selected_capability_id != GTA6_BRAIN_CAPABILITY_ID:
        raise PermissionError("gta6.brain.decide routing capability mismatch")
    if routing_decision.authorized_action != "DECISION":
        raise PermissionError("gta6.brain.decide routing action mismatch")
    if routing_decision.selected_executor_binding != GTA6_BRAIN_EXECUTOR_BINDING:
        raise PermissionError("gta6.brain.decide routing executor mismatch")
    lineage = dict(auth.lineage or {})
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("gta6.brain.decide authorization routing mismatch")
    if lineage.get("capability_id") != GTA6_BRAIN_CAPABILITY_ID:
        raise PermissionError("gta6.brain.decide authorization capability mismatch")
    if lineage.get("selected_executor_binding") != GTA6_BRAIN_EXECUTOR_BINDING:
        raise PermissionError("gta6.brain.decide authorization executor mismatch")

    mission_id = str(payload.get("mission_id") or f"gta6-brain:{auth.execution_id}").strip()
    task_id = str(payload.get("task_id") or "gta6-domain-decision").strip()
    goal_id = str(
        payload.get("goal_id")
        or lineage.get("goal_id")
        or "gta6-operational-control"
    ).strip()
    if not mission_id or not task_id or not goal_id:
        raise ValueError("mission_id, task_id and goal_id must be non-empty")

    provider_routing = route_harness_request(
        HarnessRoutingRequest(
            intent="reason over canonical GTA6 operational context and recommend exactly one next action",
            authorized_action="DECISION",
            domain="ai",
            task_class="gta6-brain-reasoning",
            goal_id=goal_id,
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    if not provider_routing.selected_provider:
        raise RuntimeError("Harness did not select a GTA6 Brain reasoning provider")

    provider_authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject=f"provider:{provider_routing.selected_provider}",
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        lineage={
            "parent_authorization_id": auth.authorization_id,
            "routing_id": provider_routing.routing_id,
            "capability_id": provider_routing.selected_capability_id,
            "selected_provider": provider_routing.selected_provider,
            "selected_model": provider_routing.selected_model,
            "selected_executor_binding": provider_routing.selected_provider_executor_binding,
            "mission_id": mission_id,
            "task_id": task_id,
            "goal_id": goal_id,
        },
    )

    started_at = datetime.now(timezone.utc).isoformat()
    try:
        _, provider = select_harness_ai_provider(
            routing_decision=provider_routing,
            authorization=provider_authorization,
        )
        decision = GTA6Brain(ai_provider=provider).decide()
    finally:
        consume_harness_authorization(provider_authorization)
    finished_at = datetime.now(timezone.utc).isoformat()

    evidence_refs = (
        f"routing:{routing_decision.routing_id}",
        f"authorization:{auth.authorization_id}",
        f"provider-routing:{provider_routing.routing_id}",
        f"provider-authorization:{provider_authorization.authorization_id}",
    )
    receipt = AgentInvocationReceipt(
        mission_id=mission_id,
        task_id=task_id,
        goal_id=goal_id,
        decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        agent_id="gta6-brain",
        capability=GTA6_BRAIN_CAPABILITY_ID,
        executor=GTA6_BRAIN_EXECUTOR_BINDING,
        provider=str(provider_routing.selected_provider),
        input_refs=tuple(str(x) for x in payload.get("input_refs") or ()),
        output_refs=(f"brain-decision:{mission_id}:{task_id}",),
        evidence_refs=evidence_refs,
        started_at=started_at,
        finished_at=finished_at,
        status="COMPLETED",
        validation_level="LIVE",
        external_call_performed=True,
        exit_code=0,
        returned_to_harness=True,
    )
    evidence = CapabilityEvidence(
        capability_id=GTA6_BRAIN_CAPABILITY_ID,
        provider=str(provider_routing.selected_provider),
        status="EXECUTED",
        active=True,
        authority=auth.authority,
        authorized_action=auth.authorized_action,
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        result={
            "brain_decision": asdict(decision),
            "receipt": receipt.to_dict(),
            "provider_routing": provider_routing.to_dict(),
            "authority": "DEEPSEEK_HARNESS",
            "execution_authorized": False,
        },
        boundary=record.security_boundary,
    )
    canonical = evidence.to_canonical_result(
        authorization_id=auth.authorization_id,
        routing_id=routing_decision.routing_id,
        tool="gta6-brain",
        operation="decide",
        model=provider_routing.selected_model,
        executor=GTA6_BRAIN_EXECUTOR_BINDING,
    )
    capture_canonical_execution_episode(
        canonical,
        routing_decision=routing_decision,
        domain=record.domain,
        task_class="gta6-domain-decision",
        skill_version=record.version,
        source_versions={f"capability:{GTA6_BRAIN_CAPABILITY_ID}": str(record.version)},
    )
    return evidence
