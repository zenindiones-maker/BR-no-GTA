from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.provider_health_service import semantic_provider_health
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


@dataclass(frozen=True)
class MissionExecutionRoute:
    runtime: str
    mission_class: str
    task_count: int
    has_dependencies: bool
    selected_capability_ids: tuple[str, ...]
    provider_required: bool
    reason: str
    hermes_used: bool = False
    hermes_selection_reason: str = "NOT_REQUIRED"
    coordination_benefit: bool = False
    durable: bool = False
    authority: str = "DEEPSEEK_HARNESS"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def select_mission_execution_route(
    mission_plan: dict[str, Any],
) -> MissionExecutionRoute:
    if not isinstance(mission_plan, dict):
        raise ValueError("Harness MissionPlan is required")
    if mission_plan.get("authority") != "DEEPSEEK_HARNESS":
        raise PermissionError("MissionPlan escaped DeepSeek Harness authority")

    goal = dict(mission_plan.get("goal") or {})
    collaboration = dict(mission_plan.get("collaboration_plan") or {})
    tasks = list(collaboration.get("tasks") or ())
    if not tasks:
        raise ValueError("MissionPlan contains no executable tasks")
    mission_class = str(goal.get("mission_class") or "").strip().upper()
    capability_ids = tuple(str(item.get("capability_id") or "") for item in tasks)
    if any(not value for value in capability_ids):
        raise ValueError("MissionPlan contains task without capability_id")

    records = []
    for capability_id in capability_ids:
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        if record is None or not record.execution_enabled:
            raise PermissionError(
                f"MissionPlan capability is not executable: {capability_id}"
            )
        records.append(record)

    task_count = len(tasks)
    has_dependencies = any(bool(item.get("dependencies")) for item in tasks)
    has_review = any(
        str(item.get("review_policy") or "").upper()
        in {"INDEPENDENT_REQUIRED", "REQUIRED"}
        or bool(getattr(record, "supports_review", False))
        and bool(item.get("write_scope"))
        for item, record in zip(tasks, records)
    )
    requires_resume = any(
        bool(getattr(record, "supports_resume", False))
        and (
            bool(item.get("dependencies"))
            or bool(item.get("write_scope"))
            or int(item.get("retry_budget") or 0) > 0
        )
        for item, record in zip(tasks, records)
    )
    all_parallel_safe = all(
        bool(getattr(record, "supports_parallelism", False))
        and str(getattr(record, "side_effect_class", "READ_ONLY"))
        in {"READ_ONLY", "COORDINATION_ONLY"}
        for record in records
    )
    distinct_owners = {
        (
            str(item.get("selected_agent_id") or ""),
            str(item.get("selected_skill_id") or ""),
            item["capability_id"],
        )
        for item in tasks
    }
    coordination_benefit = (
        task_count > 1
        and (
            has_dependencies
            or len(distinct_owners) > 1
            or all_parallel_safe
            or has_review
        )
    )

    if task_count == 1:
        record = records[0]
        if (
            record.capability_id.startswith("agent-office.")
            or record.domain == "development"
            and record.agent_id is not None
        ):
            return MissionExecutionRoute(
                runtime="AGENT_OFFICE",
                mission_class=mission_class,
                task_count=1,
                has_dependencies=False,
                selected_capability_ids=capability_ids,
                provider_required=False,
                reason=(
                    "single bounded engineering task is sufficiently owned by "
                    "the Agent Office execution boundary"
                ),
                hermes_used=False,
                hermes_selection_reason="single task; coordination overhead avoided",
            )
        if record.executor_binding and record.capability_type != "PROVIDER":
            return MissionExecutionRoute(
                runtime="DIRECT_CAPABILITY",
                mission_class=mission_class,
                task_count=1,
                has_dependencies=False,
                selected_capability_ids=capability_ids,
                provider_required=False,
                reason="single Registry executor is sufficient",
                hermes_used=False,
                hermes_selection_reason="single direct task; Hermes adds no coordination value",
            )

    if task_count > 1 and (has_dependencies or has_review or requires_resume):
        return MissionExecutionRoute(
            runtime="HERMES_KANBAN",
            mission_class=mission_class,
            task_count=task_count,
            has_dependencies=has_dependencies,
            selected_capability_ids=capability_ids,
            provider_required=False,
            reason=(
                "dependency/review/resume requirements need durable delegated "
                "coordination and bounded task lifecycle"
            ),
            hermes_used=True,
            hermes_selection_reason=(
                "dependency DAG, independent review or durable resume is required"
            ),
            coordination_benefit=True,
            durable=True,
        )

    if task_count > 1 and coordination_benefit:
        return MissionExecutionRoute(
            runtime="HERMES_COLLABORATION",
            mission_class=mission_class,
            task_count=task_count,
            has_dependencies=False,
            selected_capability_ids=capability_ids,
            provider_required=False,
            reason=(
                "multiple independent task owners benefit from bounded parallel "
                "coordination and a deterministic join"
            ),
            hermes_used=True,
            hermes_selection_reason=(
                "multiple independent capabilities can coordinate without authority expansion"
            ),
            coordination_benefit=True,
            durable=False,
        )

    # Semantic execution is a last resort only when the selected task does not
    # have a deterministic Registry executor.
    health = semantic_provider_health()
    if health.get("semantic_reasoning_available"):
        return MissionExecutionRoute(
            runtime="SEMANTIC_PROVIDER",
            mission_class=mission_class,
            task_count=task_count,
            has_dependencies=has_dependencies,
            selected_capability_ids=capability_ids,
            provider_required=True,
            reason=(
                "no deterministic executor is sufficient and healthy semantic "
                "reasoning is required"
            ),
            hermes_used=False,
            hermes_selection_reason="semantic reasoning does not require coordination",
        )
    return MissionExecutionRoute(
        runtime="SEMANTIC_PROVIDER_UNAVAILABLE",
        mission_class=mission_class,
        task_count=task_count,
        has_dependencies=has_dependencies,
        selected_capability_ids=capability_ids,
        provider_required=True,
        reason="semantic-only task has no healthy provider",
        hermes_used=False,
        hermes_selection_reason="no executable coordination topology is available",
    )

def _direct_task_payload(
    *,
    task: TaskEnvelope,
    mission_plan: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    goal = dict(mission_plan.get("goal") or {})
    objective = str(task.objective or message or goal.get("human_goal") or "").strip()
    return {
        "mission_id": str(mission_plan.get("mission_id") or ""),
        "task_id": task.task_id,
        "goal_id": str(goal.get("goal_id") or task.goal_id or ""),
        "task_class": task.task_class,
        "objective": objective,
        "task": objective,
        "query": str(message or goal.get("human_goal") or objective).strip(),
        "gaps": [objective] if objective else [],
        "input_refs": list(task.input_refs),
        "read_scope": list(task.read_scope),
        "write_scope": list(task.write_scope),
        "allowed_tools": list(task.allowed_tools),
        "allowed_side_effects": list(task.allowed_side_effects),
        "forbidden_side_effects": list(task.forbidden_side_effects),
        "acceptance_criteria": list(task.acceptance_criteria),
        "expected_output": task.expected_output,
        "evidence_contract": task.evidence_contract,
        "time_budget_seconds": task.time_budget_seconds,
        "cost_budget": task.cost_budget,
        "context_budget_bytes": task.context_budget_bytes,
        "tool_budget": task.tool_budget,
        "retry_budget": task.retry_budget,
        "idempotency_key": task.idempotency_key,
        "limit": 10,
        "max_context_bytes": min(task.context_budget_bytes, 32768),
    }


def _execute_direct_capability(
    *,
    mission_plan: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    collaboration = dict(mission_plan.get("collaboration_plan") or {})
    task_rows = list(collaboration.get("tasks") or ())
    if len(task_rows) != 1:
        raise ValueError("direct capability route requires exactly one task")
    task = TaskEnvelope.from_mapping(dict(task_rows[0]))
    record = GLOBAL_CAPABILITY_REGISTRY.get(task.capability_id)
    if record is None or not record.execution_enabled:
        raise PermissionError("direct task capability is not executable")

    goal = dict(mission_plan.get("goal") or {})
    decision = route_harness_request(HarnessRoutingRequest(
        intent=f"direct TaskEnvelope {task.task_id}: {task.objective}",
        authorized_action=task.action,
        domain=record.domain,
        task_class=task.task_class,
        goal_id=str(goal.get("goal_id") or task.goal_id or ""),
        required_capability_id=task.capability_id,
        fallback_allowed=False,
        provider_required=False,
        learning_required=True,
    ))
    if decision.selected_capability_id != task.capability_id:
        raise PermissionError("direct route capability substitution requires Harness replan")
    if decision.selected_executor_binding != record.executor_binding:
        raise PermissionError("direct route executor escaped Registry")

    adapter = CapabilityAdapter()
    executor = adapter.resolve_binding(str(record.executor_binding or ""))
    authorization = issue_harness_authorization(
        authorized_action=task.action,
        subject=adapter.authorization_subject(executor, task),
        execution_id=(
            f"{mission_plan.get('mission_id')}:{task.task_id}:direct"
        ),
        lineage={
            "mission_id": mission_plan.get("mission_id"),
            "plan_id": mission_plan.get("plan_id"),
            "task_id": task.task_id,
            "task_class": task.task_class,
            "goal_id": goal.get("goal_id"),
            "capability_id": task.capability_id,
            "capability_version": str(record.version or "1"),
            "routing_id": decision.routing_id,
            "selected_executor_binding": record.executor_binding,
            "agent_id": record.agent_id,
            "skill_id": record.skill_id,
            "parent_authorization_id": None,
            "idempotency_key": task.idempotency_key,
            "read_scope": list(task.read_scope),
            "write_scope": list(task.write_scope),
            "time_budget_seconds": task.time_budget_seconds,
            "cost_budget": task.cost_budget,
            "context_budget_bytes": task.context_budget_bytes,
            "tool_budget": task.tool_budget,
            "retry_budget": task.retry_budget,
            "expires_at": task.expires_at,
            "topology": "DIRECT_CAPABILITY",
        },
    )
    try:
        adapted = adapter.execute(
            authorization=authorization,
            task_envelope=task,
            routing_decision=decision,
            payload=_direct_task_payload(
                task=task,
                mission_plan=mission_plan,
                message=message,
            ),
        )
    finally:
        consume_harness_authorization(authorization)
    return {
        "status": "COMPLETED",
        "authority": "DEEPSEEK_HARNESS",
        "capability_id": task.capability_id,
        "agent_id": record.agent_id,
        "routing_id": decision.routing_id,
        "authorization_id": authorization.authorization_id,
        "executor_binding": record.executor_binding,
        "result": adapted.to_dict(),
        "HERMES_USED": "NO",
        "HERMES_SELECTION_REASON": "single direct capability is sufficient",
    }


def execute_harness_mission_plan(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    mission_plan = plan.get("mission_plan")
    if not isinstance(mission_plan, dict):
        raise ValueError("natural-language mission execution requires MissionPlan")
    route = select_mission_execution_route(mission_plan)
    route_dict = route.to_dict()
    mission_goal = dict(mission_plan.get("goal") or {})

    if route.runtime in {"HERMES_COLLABORATION", "HERMES_KANBAN"}:
        from app.services.telegram_hermes_dispatch_service import (
            dispatch_telegram_hermes_mission,
        )
        result = dispatch_telegram_hermes_mission(
            plan=plan,
            state=state,
            message=message,
        )
    elif route.runtime == "DIRECT_CAPABILITY":
        result = _execute_direct_capability(
            mission_plan=mission_plan,
            message=message,
        )
    elif route.runtime == "AGENT_OFFICE":
        return {
            "status": "CLOUD_EXECUTION_REQUIRED",
            "answer": (
                "A tarefa exige o Agent Office engineering sandbox. "
                "O Harness manteve a execução no boundary cloud; nenhuma carga "
                "pesada foi iniciada neste control surface."
            ),
            "mission_execution_route": route_dict,
            "authority": "DEEPSEEK_HARNESS",
            "provider_required": False,
            "HERMES_USED": "NO",
            "HERMES_SELECTION_REASON": route.hermes_selection_reason,
            "TERMUX_HEAVY_PROCESSING": "NO",
        }
    elif route.runtime == "SEMANTIC_PROVIDER_UNAVAILABLE":
        return {
            "status": "BLOCKED_PROVIDER",
            "answer": (
                "Não consigo fazer a parte de raciocínio aberto agora porque nenhum modelo semântico "
                "zero-cost está disponível. O restante do sistema continua operacional."
            ),
            "reason_code": "SEMANTIC_REASONING_PROVIDER_UNAVAILABLE",
            "mission_execution_route": route_dict,
            "authority": "DEEPSEEK_HARNESS",
            "provider_retry_performed": False,
        }
    else:
        return {
            "status": "WAITING_FOR_HUMAN",
            "answer": "A missão exige raciocínio semântico aberto; o boundary de conversa deve executá-lo.",
            "mission_execution_route": route_dict,
            "authority": "DEEPSEEK_HARNESS",
            "provider_required": True,
        }

    return {
        **dict(result),
        "mission_execution_route": route_dict,
        "MISSION_EXECUTION_ROUTER": "PASS",
        "HERMES_USED": "YES" if route.hermes_used else "NO",
        "HERMES_SELECTION_REASON": route.hermes_selection_reason,
        "provider_substituted_for_known_executor": False,
    }
