from __future__ import annotations

import json
from typing import Any

from app.services.editorial_queue_consumer import process_next_editorial_queue_item
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_ai_provider_service import (
    execute_harness_ai_generation,
    select_harness_ai_provider,
)
from app.services.harness_authorization_service import (
    authorization_to_context,
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.provider_health_service import semantic_provider_health
from app.services.telegram_fresh_research_service import (
    execute_fresh_gta6_research_capability,
)
from app.services.telegram_group_human_surface_service import (
    deliver_script_human_review_ready,
)


EDITORIAL_PROCESS_CAPABILITY_ID = "editorial.process"
EDITORIAL_PROCESS_TASK_BINDING = (
    "app.services.production_mission_capability_adapters."
    "execute_editorial_process_task"
)
FRESH_RESEARCH_CAPABILITY_ID = "gta6.research.fresh-cloud"
FRESH_RESEARCH_TASK_BINDING = (
    "app.services.production_mission_capability_adapters."
    "execute_fresh_research_task"
)
RESEARCH_SEMANTIC_CAPABILITY_ID = "gta6.research.semantic-synthesis"
RESEARCH_SEMANTIC_TASK_BINDING = (
    "app.services.production_mission_capability_adapters."
    "execute_research_semantic_synthesis_task"
)
TELEGRAM_REVIEW_CAPABILITY_ID = "telegram.review.deliver"
TELEGRAM_REVIEW_TASK_BINDING = (
    "app.services.production_mission_capability_adapters."
    "execute_telegram_review_delivery_task"
)


def _dependency_artifact_context(
    payload: dict[str, Any],
    *,
    required: bool = True,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    context = payload.get("context")
    if not isinstance(context, dict):
        if required:
            raise ValueError("TaskEnvelope dependency artifact context is required")
        return [], ()
    parents = [
        dict(item)
        for item in (context.get("parent_handoffs") or ())
        if isinstance(item, dict) and item.get("direct_dependency") is True
    ]
    if required and not parents:
        raise ValueError("direct dependency artifact is required")
    refs: list[str] = []
    for parent in parents:
        task_result_ref = str(parent.get("task_result_ref") or "").strip()
        digest = str(parent.get("content_sha256") or "").strip()
        if not task_result_ref.startswith("artifact:"):
            raise ValueError("dependency task_result_ref must be a persisted artifact ref")
        if len(digest) != 64:
            raise ValueError("dependency artifact content hash is required")
        for raw_ref in (
            task_result_ref,
            *(parent.get("output_artifact_refs") or ()),
            *(parent.get("evidence_refs") or ()),
        ):
            value = str(raw_ref or "").strip()
            if value and value not in refs:
                refs.append(value)
    return parents, tuple(refs)


def _selected_zero_cost_providers() -> tuple[str, ...]:
    health = semantic_provider_health()
    providers = tuple(
        str(item)
        for item in (health.get("eligible_zero_cost_provider_ids") or ())
        if str(item).strip()
    )
    if not providers:
        raise RuntimeError("SEMANTIC_REASONING_PROVIDER_UNAVAILABLE")
    return providers


def execute_fresh_research_task(
    *,
    authorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    auth = validate_harness_authorization(
        authorization,
        expected_action="RESEARCH",
        expected_subject=f"capability:{FRESH_RESEARCH_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(FRESH_RESEARCH_CAPABILITY_ID)
    if record is None or record.executor_binding != FRESH_RESEARCH_TASK_BINDING:
        raise PermissionError("fresh research task adapter escaped Registry")
    if routing_decision.selected_capability_id != FRESH_RESEARCH_CAPABILITY_ID:
        raise PermissionError("fresh research task capability mismatch")
    if routing_decision.selected_executor_binding != FRESH_RESEARCH_TASK_BINDING:
        raise PermissionError("fresh research task executor mismatch")

    query = str(payload.get("query") or payload.get("objective") or "").strip()
    if not query:
        raise ValueError("fresh research task requires query")
    evidence = execute_fresh_gta6_research_capability(
        query=query,
        authorization=auth,
        routing_decision=routing_decision,
        source_context=(
            dict(payload.get("source_context"))
            if isinstance(payload.get("source_context"), dict)
            else None
        ),
    )
    return evidence.to_dict()


def execute_editorial_process_task(
    *,
    authorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """TaskEnvelope adapter for the canonical AI-backed editorial consumer.

    The adapter does not choose a team or executor. It only translates the
    Harness-selected editorial task into the legacy action-scoped consumer
    contract while preserving the parent authorization lineage.
    """
    auth = validate_harness_authorization(
        authorization,
        expected_action="EDITORIAL",
        expected_subject=f"capability:{EDITORIAL_PROCESS_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(EDITORIAL_PROCESS_CAPABILITY_ID)
    if record is None or record.executor_binding != EDITORIAL_PROCESS_TASK_BINDING:
        raise PermissionError("editorial task adapter escaped Registry")
    if routing_decision.selected_capability_id != EDITORIAL_PROCESS_CAPABILITY_ID:
        raise PermissionError("editorial task capability mismatch")
    if routing_decision.selected_executor_binding != EDITORIAL_PROCESS_TASK_BINDING:
        raise PermissionError("editorial task executor mismatch")

    _, dependency_refs = _dependency_artifact_context(payload, required=True)

    target_goal_id = str(
        payload.get("target_goal_id") or payload.get("goal_id") or ""
    ).strip()
    if not target_goal_id:
        raise ValueError("editorial task requires target_goal_id")

    duration = payload.get("target_duration_seconds")
    if duration is not None:
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ValueError("target_duration_seconds must be numeric")
        duration = float(duration)
        if duration <= 0:
            raise ValueError("target_duration_seconds must be positive")

    editorial_context = payload.get("editorial_context")
    if editorial_context is not None and not isinstance(editorial_context, dict):
        raise ValueError("editorial_context must be an object")

    provider_routing = route_harness_request(
        HarnessRoutingRequest(
            intent=(
                "produce the evidence-grounded GTA6 editorial script for the "
                "Harness-selected Goal"
            ),
            authorized_action="EDITORIAL",
            # This is the nested semantic-provider route. Keep the outer
            # task/domain editorial.process, but route provider selection in
            # the canonical AI domain just like research synthesis.
            domain="ai",
            task_class="production-mission-editorial",
            goal_id=target_goal_id,
            # Provider construction is governed by the canonical AI
            # capability. The parent task remains editorial.process; this
            # nested route only selects the semantic provider/model.
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            preferred_providers=_selected_zero_cost_providers(),
            required_model_capabilities=("reasoning",),
            prefer_low_latency=True,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    if not provider_routing.selected_provider:
        raise RuntimeError("Harness did not select an editorial semantic provider")

    provider_authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject=f"provider:{provider_routing.selected_provider}",
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        lineage={
            "parent_authorization_id": auth.authorization_id,
            "routing_id": provider_routing.routing_id,
            "capability_id": provider_routing.selected_capability_id,
            "selected_provider": provider_routing.selected_provider,
            "selected_model": provider_routing.selected_model,
            "selected_executor_binding": (
                provider_routing.selected_provider_executor_binding
            ),
            "goal_id": target_goal_id,
        },
    )
    action_authorization = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="action:EDITORIAL",
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        lineage={
            "parent_authorization_id": auth.authorization_id,
            "provider_authorization_id": provider_authorization.authorization_id,
            "routing_id": provider_routing.routing_id,
            "selected_capability_id": EDITORIAL_PROCESS_CAPABILITY_ID,
            "selected_provider": provider_routing.selected_provider,
            "selected_model": provider_routing.selected_model,
            "selected_executor_binding": EDITORIAL_PROCESS_TASK_BINDING,
            "goal_id": target_goal_id,
            "target_duration_seconds": duration,
        },
    )
    try:
        _, provider = select_harness_ai_provider(
            routing_decision=provider_routing,
            authorization=provider_authorization,
        )
        result = process_next_editorial_queue_item(
            ai_provider=provider,
            execution_context=authorization_to_context(action_authorization),
            goal_id=target_goal_id,
            editorial_context=dict(editorial_context or {}),
        )
    finally:
        consume_harness_authorization(action_authorization)
        consume_harness_authorization(provider_authorization)

    if result is None:
        raise RuntimeError(
            "Harness-selected editorial Goal has no queued editorial work"
        )
    normalized = dict(result)
    if normalized.get("status") != "completed":
        raise RuntimeError(
            "Harness-selected editorial task did not complete"
        )
    script_id = int((normalized.get("script") or {}).get("id") or 0)
    content_item_id = int((normalized.get("content_item") or {}).get("id") or 0)
    production_plan_id = int(normalized.get("production_plan_id") or 0)
    if script_id <= 0 or content_item_id <= 0 or production_plan_id <= 0:
        raise RuntimeError("editorial task did not persist complete production artifacts")
    normalized["task_adapter"] = "production-mission/v1"
    normalized["parent_authorization_id"] = auth.authorization_id
    normalized["provider_routing"] = provider_routing.to_dict()
    normalized["input_refs"] = list(dependency_refs)
    normalized["artifact_refs"] = [
        f"script:{script_id}",
        f"content-item:{content_item_id}",
        f"production-plan:{production_plan_id}",
    ]
    return normalized

def execute_research_semantic_synthesis_task(
    *,
    authorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Reason over persisted research artifacts without granting semantics to collectors."""
    auth = validate_harness_authorization(
        authorization,
        expected_action="RESEARCH",
        expected_subject=f"capability:{RESEARCH_SEMANTIC_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(RESEARCH_SEMANTIC_CAPABILITY_ID)
    if record is None or record.executor_binding != RESEARCH_SEMANTIC_TASK_BINDING:
        raise PermissionError("semantic research adapter escaped Registry")
    if routing_decision.selected_capability_id != RESEARCH_SEMANTIC_CAPABILITY_ID:
        raise PermissionError("semantic research capability mismatch")
    if routing_decision.selected_executor_binding != RESEARCH_SEMANTIC_TASK_BINDING:
        raise PermissionError("semantic research executor mismatch")

    parents, dependency_refs = _dependency_artifact_context(payload, required=True)
    parent_payloads = [
        {
            "task_id": item.get("task_id"),
            "capability_id": item.get("capability_id"),
            "result_summary": item.get("result_summary"),
            "result": item.get("result"),
            "evidence_refs": list(item.get("evidence_refs") or ())[:12],
        }
        for item in parents
    ]
    context_text = json.dumps(
        parent_payloads,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    if len(context_text) > 22000:
        context_text = context_text[:22000]

    goal_id = str(
        payload.get("goal_id")
        or auth.lineage.get("goal_id")
        or ""
    ).strip()
    provider_routing = route_harness_request(
        HarnessRoutingRequest(
            intent=(
                "analyze fresh GTA6 research artifacts and synthesize a current "
                "evidence-grounded editorial angle"
            ),
            authorized_action="RESEARCH",
            domain="ai",
            task_class="production-research-semantic-synthesis",
            goal_id=goal_id or None,
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            preferred_providers=_selected_zero_cost_providers(),
            required_model_capabilities=("reasoning",),
            structured_output_required=True,
            prefer_low_latency=True,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    if not provider_routing.selected_provider:
        raise RuntimeError("Harness did not select a semantic research provider")
    provider_authorization = issue_harness_authorization(
        authorized_action="RESEARCH",
        subject=f"provider:{provider_routing.selected_provider}",
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        lineage={
            "parent_authorization_id": auth.authorization_id,
            "routing_id": provider_routing.routing_id,
            "capability_id": provider_routing.selected_capability_id,
            "selected_provider": provider_routing.selected_provider,
            "selected_model": provider_routing.selected_model,
            "selected_executor_binding": (
                provider_routing.selected_provider_executor_binding
            ),
            "goal_id": goal_id or None,
            "input_refs": list(dependency_refs),
        },
    )
    prompt = (
        "You are a subordinate GTA6 research synthesis specialist. "
        "DeepSeek Harness is the sole authority. Analyze only the persisted "
        "dependency artifacts below. Do not collect new sources, do not invent "
        "facts, and distinguish verified evidence from inference. Return ONLY "
        "JSON with keys topic, why_now, strongest_findings, risks, evidence_refs. "
        "strongest_findings/risks/evidence_refs must be arrays of strings.\n\n"
        f"OBJECTIVE={str(payload.get('objective') or '').strip()}\n"
        f"DEPENDENCY_ARTIFACTS={context_text}"
    )
    try:
        evidence = execute_harness_ai_generation(
            prompt=prompt,
            authorization=provider_authorization,
            routing_decision=provider_routing,
        )
    finally:
        consume_harness_authorization(provider_authorization)
    if evidence.status != "EXECUTED" or not isinstance(evidence.result, dict):
        raise RuntimeError("semantic research provider did not execute")
    raw = str(evidence.result.get("text") or "").strip()
    fence = chr(96) * 3
    if raw.startswith(fence):
        lines = raw.splitlines()
        lines = lines[1:] if lines else lines
        if lines and lines[-1].strip().startswith(fence):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
    try:
        semantic_output = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("semantic research output is not valid JSON") from exc
    if not isinstance(semantic_output, dict):
        raise RuntimeError("semantic research output must be an object")
    mission_id = str(
        payload.get("mission_id")
        or auth.lineage.get("mission_id")
        or auth.execution_id
    )
    task_id = str(payload.get("task_id") or "research-semantic")
    return {
        "status": "EXECUTED",
        "semantic_output": semantic_output,
        "semantic_provider": evidence.provider,
        "semantic_model": evidence.model,
        "semantic_evidence": evidence.to_dict(),
        "input_refs": list(dependency_refs),
        "evidence_refs": list(dict.fromkeys([
            *dependency_refs,
            *tuple(evidence.evidence_refs),
        ])),
        "output_ref": f"research-semantic:{mission_id}:{task_id}",
        "provider_routing": provider_routing.to_dict(),
    }


def execute_telegram_review_delivery_task(
    *,
    authorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Canonical outbound Telegram review adapter; never used for ingress."""
    auth = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{TELEGRAM_REVIEW_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(TELEGRAM_REVIEW_CAPABILITY_ID)
    if record is None or record.executor_binding != TELEGRAM_REVIEW_TASK_BINDING:
        raise PermissionError("Telegram outbound adapter escaped Registry")
    if routing_decision.selected_capability_id != TELEGRAM_REVIEW_CAPABILITY_ID:
        raise PermissionError("Telegram outbound capability mismatch")
    if routing_decision.selected_executor_binding != TELEGRAM_REVIEW_TASK_BINDING:
        raise PermissionError("Telegram outbound executor mismatch")
    _, dependency_refs = _dependency_artifact_context(payload, required=True)

    child = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="human-surface:telegram_group",
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        lineage={
            "parent_authorization_id": auth.authorization_id,
            "routing_id": routing_decision.routing_id,
            "capability_id": TELEGRAM_REVIEW_CAPABILITY_ID,
            "goal_id": payload.get("goal_id"),
            "input_refs": list(dependency_refs),
            "direction": "HARNESS_TO_TELEGRAM_HUMAN",
        },
    )
    try:
        result = deliver_script_human_review_ready(
            authorization=child,
            editorial_summary=str(payload.get("editorial_summary") or ""),
            evidence_map=str(payload.get("evidence_map") or ""),
            outline=str(payload.get("outline") or ""),
            complete_script=str(payload.get("complete_script") or ""),
            lineage=(
                dict(payload.get("lineage"))
                if isinstance(payload.get("lineage"), dict)
                else None
            ),
        )
    finally:
        consume_harness_authorization(child)
    if result.get("status") != "SENT":
        raise RuntimeError("Telegram outbound human review delivery failed closed")
    deliveries = list(result.get("deliveries") or ())
    message_refs = [
        f"telegram-message:{item.get('message_id')}"
        for item in deliveries
        if isinstance(item, dict) and item.get("message_id") is not None
    ]
    if not message_refs:
        message_refs = [f"telegram-review:{auth.execution_id}"]
    return {
        **dict(result),
        "direction": "HARNESS_TO_TELEGRAM_HUMAN",
        "input_refs": list(dependency_refs),
        "artifact_refs": message_refs,
        "TELEGRAM_INGRESS_NOT_USED_FOR_DELIVERY": "PASS",
        "TELEGRAM_OUTBOUND_BOUNDARY_VALID": "PASS",
    }
