from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.provider_health_service import semantic_provider_health
from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_adaptive_planning_service import select_capability_for_requirement
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


def _persist_execution_need(
    *,
    mission_plan: dict[str, Any],
    need: dict[str, Any],
    artifact_dir: str | Path,
) -> dict[str, Any]:
    """Persist an executor need before Harness changes mission execution state."""
    if str(need.get("schema") or "") != "HarnessExecutionNeed/v1":
        raise ValueError("HarnessExecutionNeed/v1 is required")
    mission_id = str(mission_plan.get("mission_id") or "").strip()
    causal_task_id = str(need.get("causal_task_id") or "").strip()
    if not mission_id or not causal_task_id:
        raise ValueError("execution need requires mission_id and causal_task_id")
    canonical = {
        **dict(need),
        "mission_id": mission_id,
        "authority": "DEEPSEEK_HARNESS",
        "producer_selected_resolver": False,
    }
    raw = json.dumps(
        canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = sha256(raw).hexdigest()
    root = Path(artifact_dir) / "harness-execution-needs"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{mission_id}-{causal_task_id}-{digest[:16]}.json"
    if not path.exists():
        path.write_bytes(raw)
    return {
        "need_ref": f"artifact:harness-execution-need:{digest}",
        "path": str(path),
        "sha256": digest,
        "need": canonical,
    }


def resolve_harness_execution_need(
    *,
    mission_plan: dict[str, Any],
    need: dict[str, Any],
    planning_context: dict[str, Any],
    artifact_dir: str | Path,
    used_capability_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Canonical Harness receiver for executor needs.

    Executors describe what is missing. Harness alone persists the need, decides
    RETRY versus REPLAN, and resolves any new semantic capability requirement.
    """
    persisted = _persist_execution_need(
        mission_plan=mission_plan,
        need=need,
        artifact_dir=artifact_dir,
    )
    typed = dict(persisted["need"])
    retryable = str(typed.get("retryability") or "").upper() == "RETRYABLE"
    replan_required = bool(typed.get("replan_required"))
    failure_class = str(typed.get("failure_class") or "").upper()
    if failure_class in {
        "INSUFFICIENT_EVIDENCE",
        "TASKOUTPUTCONTRACTVIOLATION",
        "ROUTINGPOLICYERROR",
    }:
        replan_required = True
    decision = "REPLAN" if replan_required else "RETRY" if retryable else "BLOCK"
    state_update = {
        "schema": "HarnessMissionStateTransition/v1",
        "authority": "DEEPSEEK_HARNESS",
        "mission_id": str(mission_plan.get("mission_id") or ""),
        "causal_task_id": str(typed.get("causal_task_id") or ""),
        "need_ref": persisted["need_ref"],
        "decision": decision,
        "preserve_completed_results": True,
        "resume_scope": "MINIMAL_AFFECTED_SUBGRAPH",
    }
    if decision != "REPLAN":
        return {
            "persisted_need": persisted,
            "mission_state_update": state_update,
            "resolution": None,
        }

    semantic_requirement = str(typed.get("semantic_requirement") or "").strip()
    if not semantic_requirement:
        raise ValueError("REPLAN requires semantic_requirement")
    requirement = {
        "task_id": f"need-{persisted['sha256'][:12]}",
        "action": "READ",
        "authorized_action": "READ",
        "task_class": "evidence-recovery",
        "functional_role": "EVIDENCE",
        "required_capability_description": semantic_requirement,
        "objective": semantic_requirement,
        "query": " ".join([
            semantic_requirement,
            *[
                str(item)
                for item in (typed.get("missing_requirements") or ())
                if str(item).strip()
            ],
        ]).strip(),
        "expected_output": "verified evidence artifacts satisfying the missing requirements",
        "input_refs": list(typed.get("produced_artifact_refs") or ()),
        "risk_side_effect_class": "READ_ONLY",
        "candidate_requirement": "NOT_APPLICABLE",
        "dependencies": [str(typed.get("causal_task_id") or "")],
    }
    capability_id, competence_used, avoided, selection = (
        select_capability_for_requirement(
            requirement,
            context=dict(planning_context),
            used=set(used_capability_ids or ()),
        )
    )
    prior_capability = str(typed.get("failed_capability_id") or "").strip()
    if prior_capability and capability_id == prior_capability:
        raise RuntimeError(
            "HARNESS_REPLAN_REPEATED_FAILED_ROUTE_WITHOUT_NEW_CAUSAL_INFORMATION"
        )
    return {
        "persisted_need": persisted,
        "mission_state_update": {
            **state_update,
            "semantic_requirement": semantic_requirement,
            "resolved_capability_id": capability_id,
        },
        "resolution": {
            "required_capability": semantic_requirement,
            "selected_capability_id": capability_id,
            "selected_by_competence": bool(competence_used),
            "avoided_paths": list(avoided),
            "selection": dict(selection),
            "producer_selected_resolver": False,
        },
    }


def execute_harness_execution_need(
    *,
    mission_plan: dict[str, Any],
    need: dict[str, Any],
    planning_context: dict[str, Any],
    artifact_dir: str | Path,
    execute_resolved_capability,
    used_capability_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Drive a persisted executor need through the canonical Harness lifecycle.

    The callback is an execution boundary only: Harness has already selected the
    capability. It cannot substitute the selected capability or downstream
    executor.
    """
    resolution = resolve_harness_execution_need(
        mission_plan=mission_plan,
        need=need,
        planning_context=planning_context,
        artifact_dir=artifact_dir,
        used_capability_ids=used_capability_ids,
    )
    transition = dict(resolution["mission_state_update"])
    lifecycle_dir = Path(artifact_dir) / "harness-mission-state"
    lifecycle_dir.mkdir(parents=True, exist_ok=True)
    transition_raw = json.dumps(
        transition, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    transition_sha = sha256(transition_raw).hexdigest()
    transition_path = lifecycle_dir / (
        f"{transition['mission_id']}-{transition['causal_task_id']}-"
        f"{transition_sha[:16]}.json"
    )
    if not transition_path.exists():
        transition_path.write_bytes(transition_raw)

    decision = str(transition["decision"])
    if decision in {"BLOCK", "RETRY"}:
        return {
            **resolution,
            "mission_state_ref": f"artifact:harness-mission-state:{transition_sha}",
            "execution": None,
        }

    selected = dict(resolution.get("resolution") or {})
    selected_capability_id = str(selected.get("selected_capability_id") or "")
    if not selected_capability_id:
        raise RuntimeError("Harness REPLAN did not resolve a capability")
    execution = execute_resolved_capability(
        selected_capability_id=selected_capability_id,
        semantic_requirement=str(selected.get("required_capability") or ""),
        causal_task_id=str(transition["causal_task_id"]),
        need_ref=str(resolution["persisted_need"]["need_ref"]),
        input_artifact_refs=tuple(
            str(item)
            for item in (need.get("produced_artifact_refs") or ())
            if str(item).strip()
        ),
    )
    if not isinstance(execution, dict):
        raise TypeError("resolved capability execution must return a typed mapping")
    observed_capability = str(execution.get("capability_id") or "")
    if observed_capability and observed_capability != selected_capability_id:
        raise PermissionError(
            "executor substituted capability after Harness resolution"
        )
    task_result_ref = str(
        execution.get("task_result_ref")
        or execution.get("evidence_ref")
        or ""
    ).strip()
    if not task_result_ref:
        raise RuntimeError("resolved execution did not persist TaskResult evidence")
    resumed = {
        **transition,
        "decision": "RESUME",
        "resolved_capability_id": selected_capability_id,
        "resolved_task_result_ref": task_result_ref,
        "dependency_updated": True,
        "next_task_ready": str(transition["causal_task_id"]),
        "result_consumption_required": True,
        "resume_scope": "MINIMAL_AFFECTED_SUBGRAPH",
    }
    resumed_raw = json.dumps(
        resumed, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    resumed_sha = sha256(resumed_raw).hexdigest()
    resumed_path = lifecycle_dir / (
        f"{resumed['mission_id']}-{resumed['causal_task_id']}-"
        f"{resumed_sha[:16]}.json"
    )
    if not resumed_path.exists():
        resumed_path.write_bytes(resumed_raw)
    return {
        **resolution,
        "mission_state_update": resumed,
        "mission_state_ref": f"artifact:harness-mission-state:{resumed_sha}",
        "execution": dict(execution),
        "lifecycle_events": (
            "RESULT_PRODUCED",
            "RESULT_PERSISTED",
            "DEPENDENCY_UPDATED",
            "NEXT_TASK_READY",
        ),
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
        if route.mission_class == "SYSTEM_IMPROVEMENT":
            from app.services.telegram_system_improvement_dispatch_service import (
                dispatch_telegram_system_improvement_mission,
            )
            result = dispatch_telegram_system_improvement_mission(
                plan=plan,
                state=state,
                message=message,
            )
        else:
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
