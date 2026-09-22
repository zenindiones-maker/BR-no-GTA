from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.provider_health_service import semantic_provider_health


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
    elif route.runtime in {"DIRECT_CAPABILITY", "AGENT_OFFICE"}:
        return {
            "status": "WAITING_FOR_HUMAN",
            "answer": (
                "O Harness encontrou um executor direto, mas o plano ainda não contém um payload "
                "operacional aprovado suficiente para executá-lo sem inventar parâmetros. "
                "Mantive a missão no boundary correto em vez de cair para um modelo semântico."
            ),
            "mission_execution_route": route_dict,
            "authority": "DEEPSEEK_HARNESS",
            "provider_required": False,
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
