from __future__ import annotations

from pathlib import Path
from typing import Any

from app.database.agent_office_mission_repository import (
    claim_mission,
    complete_mission,
    create_mission,
    get_mission,
    mark_mission_failed,
    mark_ready_for_reduction,
)
from app.services.agent_office.contracts import (
    AgentOfficeExecutionResult,
    AgentOfficeExecutionSpec,
    AgentOfficeTask,
)
from app.services.agent_office.reducer import reduce_agent_office_result
from app.services.agent_office.service import AgentOfficeService
from app.services.agent_office_harness_service import (
    AGENT_OFFICE_CAPABILITY_ID,
    AGENT_OFFICE_EXECUTOR_BINDING,
    DEFAULT_FORBIDDEN_ACTIONS,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    consume_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import HarnessRoutingDecision


def _validate_submission(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
) -> HarnessAuthorization:
    auth = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{AGENT_OFFICE_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(AGENT_OFFICE_CAPABILITY_ID)
    if record is None or record.executor_binding != AGENT_OFFICE_EXECUTOR_BINDING:
        raise PermissionError("Agent Office Registry executor mismatch")
    if routing_decision.authorized_action != "DEVELOPMENT":
        raise PermissionError("Agent Office mission requires DEVELOPMENT routing")
    if routing_decision.selected_capability_id != AGENT_OFFICE_CAPABILITY_ID:
        raise PermissionError("Agent Office mission routing capability mismatch")
    if routing_decision.selected_executor_binding != AGENT_OFFICE_EXECUTOR_BINDING:
        raise PermissionError("Agent Office mission routing executor mismatch")
    lineage = dict(auth.lineage or {})
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("Agent Office mission authorization routing mismatch")
    if lineage.get("capability_id") != AGENT_OFFICE_CAPABILITY_ID:
        raise PermissionError("Agent Office mission authorization capability mismatch")
    return auth


def submit_delegated_mission(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist one bounded mission and return immediately; no specialist runs here."""
    auth = _validate_submission(
        authorization=authorization,
        routing_decision=routing_decision,
    )
    spec_payload = dict(payload)
    spec_payload.update(
        {
            "execution_id": auth.execution_id,
            "brain_decision_id": auth.harness_decision_id,
            "harness_authorization_id": auth.authorization_id,
            "authorized_action": auth.authorized_action,
            "forbidden_actions": sorted(
                set(DEFAULT_FORBIDDEN_ACTIONS)
                | set(payload.get("forbidden_actions") or ())
            ),
        }
    )
    tasks_raw = spec_payload.pop("tasks", None)
    if not isinstance(tasks_raw, list) or not tasks_raw:
        raise ValueError("Agent Office delegated mission tasks must be a non-empty list")
    spec = AgentOfficeExecutionSpec.from_mapping(spec_payload)
    tasks = tuple(AgentOfficeTask.from_mapping(item) for item in tasks_raw)
    AgentOfficeService._validate_tasks(spec, tasks)
    request_payload = {
        "spec": spec.to_dict(),
        "tasks": [task.to_dict() for task in tasks],
        "routing": routing_decision.to_dict(),
    }
    mission = create_mission(
        mission_id=spec.mission_id,
        goal_id=spec.goal_id,
        harness_decision_id=spec.brain_decision_id,
        authorization_id=spec.harness_authorization_id,
        execution_id=spec.execution_id,
        base_sha=spec.base_sha,
        request_payload=request_payload,
    )
    return {
        "status": "DELEGATED",
        "mission_id": spec.mission_id,
        "execution_id": spec.execution_id,
        "authorization_id": spec.harness_authorization_id,
        "task_count": len(tasks),
        "base_sha": spec.base_sha,
        "harness_reactivation_required": False,
        "next_event": "MISSION_READY_FOR_REDUCTION",
        "mission_status": mission["status"],
    }


def execute_delegated_mission(
    *,
    mission_id: str,
    repository_root: str | Path,
    worker_id: str,
) -> dict[str, Any]:
    """Execution-plane claim. Uses persisted authority; it does not make a new Harness decision."""
    mission = claim_mission(mission_id, worker_id=worker_id)
    request = mission["request_payload"]
    spec = AgentOfficeExecutionSpec.from_mapping(request["spec"])
    tasks = tuple(AgentOfficeTask.from_mapping(item) for item in request["tasks"])
    try:
        result = AgentOfficeService(Path(repository_root)).execute(spec, tasks)
        ready = mark_ready_for_reduction(
            mission_id,
            result_payload=result.to_dict(),
        )
        return {
            "status": "MISSION_READY_FOR_REDUCTION",
            "mission_id": mission_id,
            "result_status": result.status,
            "artifact_refs": list(result.artifacts),
            "candidate_commits": list(result.evidence.get("candidate_commits") or ()),
            "harness_reactivation_required": True,
            "mission": ready,
        }
    except Exception as exc:
        failed = mark_mission_failed(mission_id, error=str(exc))
        return {
            "status": "TASK_FAILED",
            "mission_id": mission_id,
            "error": str(exc)[:1200],
            "harness_reactivation_required": True,
            "mission": failed,
        }


def _restore_result(payload: dict[str, Any]) -> AgentOfficeExecutionResult:
    return AgentOfficeExecutionResult(
        execution_id=str(payload["execution_id"]),
        status=str(payload["status"]),
        started_at=str(payload["started_at"]),
        finished_at=str(payload["finished_at"]),
        agents_used=tuple(payload.get("agents_used") or ()),
        tasks=tuple(payload.get("tasks") or ()),
        per_agent_results=tuple(payload.get("per_agent_results") or ()),
        files_changed=tuple(payload.get("files_changed") or ()),
        commits=tuple(payload.get("commits") or ()),
        tests=tuple(payload.get("tests") or ()),
        commands_evidence=tuple(payload.get("commands_evidence") or ()),
        artifacts=tuple(payload.get("artifacts") or ()),
        errors=tuple(payload.get("errors") or ()),
        usage=dict(payload.get("usage") or {}),
        final_summary=str(payload.get("final_summary") or ""),
        evidence=dict(payload.get("evidence") or {}),
        coordinator_role=str(payload.get("coordinator_role") or "AGENT_OFFICE_COORDINATOR"),
        authority=str(payload.get("authority") or "DELEGATED_ONLY"),
    )


def reduce_delegated_mission(
    *,
    mission_id: str,
    repository_root: str | Path,
    integration_results: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Authority-plane reactivation point: compact artifacts/evidence for accept/reject/promote."""
    mission = get_mission(mission_id)
    if mission is None:
        raise ValueError("Agent Office mission not found")
    if mission["status"] != "READY_FOR_REDUCTION":
        raise RuntimeError("Agent Office mission is not ready for reduction")
    payload = mission.get("result_payload")
    if not isinstance(payload, dict):
        raise RuntimeError("Agent Office mission has no structured result")
    result = _restore_result(payload)
    reduction = reduce_agent_office_result(
        result=result,
        repository_root=repository_root,
        integration_results=integration_results,
    )
    completed = complete_mission(
        mission_id,
        reduction_payload=reduction.to_dict(),
    )
    consume_harness_authorization(mission["authorization_id"])
    return {
        "status": reduction.status,
        "mission_id": mission_id,
        "decision_required": reduction.decision_required,
        "authority": reduction.authority,
        "canonical_push_authority": reduction.canonical_push_authority,
        "reduction": reduction.to_dict(),
        "mission_status": completed["status"],
    }
