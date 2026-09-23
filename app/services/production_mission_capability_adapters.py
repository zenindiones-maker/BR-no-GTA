from __future__ import annotations

from typing import Any

from app.services.editorial_queue_consumer import process_next_editorial_queue_item
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_ai_provider_service import select_harness_ai_provider
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
            domain="editorial",
            task_class="production-mission-editorial",
            goal_id=target_goal_id,
            required_capability_id=EDITORIAL_PROCESS_CAPABILITY_ID,
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
    normalized["task_adapter"] = "production-mission/v1"
    normalized["parent_authorization_id"] = auth.authorization_id
    normalized["provider_routing"] = provider_routing.to_dict()
    return normalized
