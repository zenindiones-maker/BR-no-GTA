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
            raise PermissionError(f"MissionPlan capability is not executable: {capability_id}")
        records.append(record)

    has_dependencies = any(bool(item.get("dependencies")) for item in tasks)
    task_count = len(tasks)

    if mission_class == "SYSTEM_IMPROVEMENT":
        return MissionExecutionRoute(
            runtime="SYSTEM_IMPROVEMENT_HERMES_AGENT_OFFICE",
            mission_class=mission_class,
            task_count=task_count,
            has_dependencies=has_dependencies,
            selected_capability_ids=capability_ids,
            provider_required=False,
            reason=(
                "development mission uses Harness-selected DAG -> Hermes collaboration -> "
                "Agent Office candidate/review boundary"
            ),
        )

    if mission_class == "GTA6_INTELLIGENCE":
        return MissionExecutionRoute(
            runtime="GTA6_RESEARCH_PIPELINE",
            mission_class=mission_class,
            task_count=task_count,
            has_dependencies=has_dependencies,
            selected_capability_ids=capability_ids,
            provider_required=False,
            reason=(
                "known GTA6 research/fact-check executors exist; semantic provider cannot replace them"
            ),
        )

    if task_count > 1 or has_dependencies:
        return MissionExecutionRoute(
            runtime="HERMES_COLLABORATION",
            mission_class=mission_class,
            task_count=task_count,
            has_dependencies=has_dependencies,
            selected_capability_ids=capability_ids,
            provider_required=False,
            reason="multi-task/dependency DAG requires governed Hermes collaboration",
        )

    record = records[0]
    if record.capability_id.startswith("agent-office."):
        return MissionExecutionRoute(
            runtime="AGENT_OFFICE",
            mission_class=mission_class,
            task_count=1,
            has_dependencies=False,
            selected_capability_ids=capability_ids,
            provider_required=False,
            reason="single development capability is owned by Agent Office boundary",
        )

    if record.executor_binding and record.capability_type != "PROVIDER":
        return MissionExecutionRoute(
            runtime="DIRECT_CAPABILITY",
            mission_class=mission_class,
            task_count=1,
            has_dependencies=False,
            selected_capability_ids=capability_ids,
            provider_required=False,
            reason="single deterministic/registered executor is sufficient",
        )

    health = semantic_provider_health()
    if health.get("semantic_reasoning_available"):
        return MissionExecutionRoute(
            runtime="SEMANTIC_PROVIDER",
            mission_class=mission_class,
            task_count=1,
            has_dependencies=False,
            selected_capability_ids=capability_ids,
            provider_required=True,
            reason="no direct executable boundary exists and healthy semantic reasoning is required",
        )
    return MissionExecutionRoute(
        runtime="SEMANTIC_PROVIDER_UNAVAILABLE",
        mission_class=mission_class,
        task_count=1,
        has_dependencies=False,
        selected_capability_ids=capability_ids,
        provider_required=True,
        reason="semantic-only task has no healthy provider",
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

    if route.runtime == "SYSTEM_IMPROVEMENT_HERMES_AGENT_OFFICE":
        from app.services.telegram_system_improvement_dispatch_service import (
            dispatch_telegram_system_improvement_mission,
        )
        result = dispatch_telegram_system_improvement_mission(
            plan=plan,
            state=state,
            message=message,
        )
    elif route.runtime == "GTA6_RESEARCH_PIPELINE":
        from app.services.telegram_gta6_query_service import execute_telegram_gta6_query
        result = execute_telegram_gta6_query(
            query=str(mission_goal.get("human_goal") or message),
            state=state,
        )
    elif route.runtime == "HERMES_COLLABORATION":
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
        "provider_substituted_for_known_executor": False,
    }
