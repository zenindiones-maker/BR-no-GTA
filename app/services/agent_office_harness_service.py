from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.agent_office.contracts import AgentOfficeExecutionSpec, AgentOfficeTask
from app.services.agent_office.service import AgentOfficeService
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
    HarnessRoutingRequest,
    route_harness_request,
)


AGENT_OFFICE_CAPABILITY_ID = "agent-office.execute"
CODEX_READONLY_CAPABILITY_ID = "agent-office.codex.readonly-analysis"
CODEX_BOUNDED_DEVELOPMENT_CAPABILITY_ID = "agent-office.codex.bounded-development"
AGENT_OFFICE_SPECIALIST_EXECUTOR_BINDING = (
    "app.services.agent_office_harness_service.execute_authorized_agent_office_specialist"
)
AGENT_OFFICE_EXECUTOR_BINDING = (
    "app.services.agent_office_harness_service.execute_agent_office_capability"
)
DEFAULT_FORBIDDEN_ACTIONS = (
    "youtube_publish",
    "autonomous_schedule",
    "push",
    "merge",
    "canonical_branch_write",
    "policy_mutation",
    "authority_mutation",
    "secret_access",
    "credential_access",
    "destructive_database_migration",
    "external_paid_action",
    "youtube_publish_public",
)


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _validate_boundary(
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
) -> HarnessAuthorization:
    authorization = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{AGENT_OFFICE_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(AGENT_OFFICE_CAPABILITY_ID)
    if record is None or record.executor_binding != AGENT_OFFICE_EXECUTOR_BINDING:
        raise PermissionError("Agent Office Registry executor mismatch")
    if routing_decision.authorized_action != "DEVELOPMENT":
        raise PermissionError("Agent Office routing action mismatch")
    if routing_decision.selected_capability_id != AGENT_OFFICE_CAPABILITY_ID:
        raise PermissionError("Agent Office routing capability mismatch")
    if routing_decision.selected_executor_binding != AGENT_OFFICE_EXECUTOR_BINDING:
        raise PermissionError("Agent Office routing executor mismatch")
    lineage = authorization.lineage
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("Agent Office authorization routing mismatch")
    if lineage.get("capability_id") != AGENT_OFFICE_CAPABILITY_ID:
        raise PermissionError("Agent Office authorization capability mismatch")
    if lineage.get("selected_executor_binding") != AGENT_OFFICE_EXECUTOR_BINDING:
        raise PermissionError("Agent Office authorization executor mismatch")
    return authorization


def execute_agent_office_capability(
    authorization: HarnessAuthorization,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
    *,
    repository_root: Path | None = None,
) -> dict[str, Any]:
    """Build the authority fields at the Harness boundary, never from worker output."""
    root = (repository_root or _repository_root()).resolve()
    spec_payload = dict(payload)
    spec_payload.update(
        {
            "execution_id": authorization.execution_id,
            "brain_decision_id": authorization.harness_decision_id,
            "harness_authorization_id": authorization.authorization_id,
            "authorized_action": authorization.authorized_action,
            "forbidden_actions": list(DEFAULT_FORBIDDEN_ACTIONS),
        }
    )
    tasks_raw = spec_payload.pop("tasks", None)
    if not isinstance(tasks_raw, list):
        raise ValueError("Agent Office tasks must be a list")
    spec = AgentOfficeExecutionSpec.from_mapping(spec_payload)
    tasks = [AgentOfficeTask.from_mapping(item) for item in tasks_raw]
    return AgentOfficeService(root).execute(spec, tasks).to_dict()


def execute_authorized_agent_office(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
    repository_root: Path | None = None,
) -> CapabilityEvidence:
    authorization = _validate_boundary(authorization, routing_decision)
    record = GLOBAL_CAPABILITY_REGISTRY.get(AGENT_OFFICE_CAPABILITY_ID)
    assert record is not None
    try:
        result = execute_agent_office_capability(
            authorization,
            routing_decision,
            payload,
            repository_root=repository_root,
        )
    except (PermissionError, ValueError):
        raise
    except Exception:
        return CapabilityEvidence(
            capability_id=AGENT_OFFICE_CAPABILITY_ID,
            provider=record.provider,
            status="FAILED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={"error": "Agent Office executor failed"},
            boundary="Agent Office failed; no fallback or authority escalation executed",
        )
    return CapabilityEvidence(
        capability_id=AGENT_OFFICE_CAPABILITY_ID,
        provider=record.provider,
        status="EXECUTED" if result["status"] in {"SUCCEEDED", "PARTIAL"} else "FAILED",
        active=result["status"] in {"SUCCEEDED", "PARTIAL"},
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id,
        result=result,
        boundary=record.security_boundary,
    )


def execute_authorized_agent_office_specialist(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
    repository_root: Path | None = None,
) -> CapabilityEvidence:
    """Run one Codex specialist through Agent Office under the existing Harness decision.

    This derives a child Agent Office authorization deterministically; it does not
    ask the Harness for a second semantic decision and cannot expand the caller's scope.
    """
    capability_id = str(routing_decision.selected_capability_id or "")
    if capability_id not in {
        CODEX_READONLY_CAPABILITY_ID,
        CODEX_BOUNDED_DEVELOPMENT_CAPABILITY_ID,
    }:
        raise PermissionError("unsupported Agent Office specialist capability")
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    if record is None or record.executor_binding != AGENT_OFFICE_SPECIALIST_EXECUTOR_BINDING:
        raise PermissionError("Agent Office specialist Registry binding mismatch")
    auth = validate_harness_authorization(
        authorization,
        expected_action="DEVELOPMENT",
        expected_subject=f"capability:{capability_id}",
    )
    if routing_decision.authorized_action != "DEVELOPMENT":
        raise PermissionError("Agent Office specialist routing action mismatch")
    if routing_decision.selected_executor_binding != AGENT_OFFICE_SPECIALIST_EXECUTOR_BINDING:
        raise PermissionError("Agent Office specialist routing executor mismatch")

    goal_id = str(payload.get("goal_id") or auth.lineage.get("goal_id") or "").strip()
    if not goal_id:
        raise ValueError("Agent Office specialist requires goal_id")
    mission_id = str(payload.get("mission_id") or auth.execution_id).strip()
    task_id = str(payload.get("task_id") or capability_id.rsplit(".", 1)[-1]).strip()
    if not mission_id or not task_id:
        raise ValueError("mission_id/task_id are required")

    office_routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"coordinate delegated specialist {capability_id} without authority expansion",
            authorized_action="DEVELOPMENT",
            domain="development",
            task_class=str(payload.get("task_class") or "delegated-specialist"),
            goal_id=goal_id,
            agent_id="agent-office-coordinator",
            required_capability_id=AGENT_OFFICE_CAPABILITY_ID,
            provider_required=False,
            fallback_allowed=False,
            learning_required=False,
        )
    )
    write_capable = capability_id == CODEX_BOUNDED_DEVELOPMENT_CAPABILITY_ID
    agent_id = "codex-development" if write_capable else "codex"
    allowed_paths = list(payload.get("allowed_paths") or [])
    read_set = list(payload.get("read_set") or [])
    write_set = list(payload.get("write_set") or [])
    mission_read_scope = list(
        payload.get("mission_read_scope")
        if payload.get("mission_read_scope") is not None
        else allowed_paths
    )
    mission_write_scope = list(
        payload.get("mission_write_scope")
        if payload.get("mission_write_scope") is not None
        else allowed_paths
    )
    if write_capable and (not allowed_paths or not write_set):
        raise ValueError("bounded-development requires allowed_paths and write_set")
    child_auth = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{AGENT_OFFICE_CAPABILITY_ID}",
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        lineage={
            "parent_authorization_id": auth.authorization_id,
            "routing_id": office_routing.routing_id,
            "capability_id": AGENT_OFFICE_CAPABILITY_ID,
            "selected_executor_binding": office_routing.selected_executor_binding,
            "goal_id": goal_id,
            "delegated_specialist_capability": capability_id,
            "mission_read_scope": list(mission_read_scope),
            "mission_write_scope": list(mission_write_scope),
            "scope_authority": "DEEPSEEK_HARNESS",
        },
    )

    task = {
        "task_id": task_id,
        "agent": agent_id,
        "capability": capability_id,
        "action": "edit" if write_capable else "analyze",
        "objective": str(payload.get("task") or payload.get("objective") or "").strip(),
        "role": str(payload.get("role") or "CODEX_ENGINEERING_TASK_OWNER"),
        "owned_task_class": str(payload.get("task_class") or (
            "BOUNDED_DEVELOPMENT" if write_capable else "READONLY_ANALYSIS"
        )),
        "allowed_paths": allowed_paths,
        "allowed_tools": list(payload.get("allowed_tools") or (
            ["git", "python", "pytest", "codex", "rg", "cat"]
            if write_capable
            else ["git", "codex", "rg", "cat"]
        )),
        "allowed_actions": list(payload.get("allowed_actions") or (
            ["analyze", "inspect", "test", "benchmark", "edit", "commit_candidate"]
            if write_capable
            else ["analyze", "inspect"]
        )),
        "input_artifact_refs": list(payload.get("input_artifact_refs") or []),
        "expected_outputs": list(payload.get("expected_outputs") or ["structured_result"]),
        "acceptance_criteria": list(payload.get("acceptance_criteria") or ["no authority expansion"]),
        "evidence_requirements": list(payload.get("evidence_requirements") or ["commands", "artifact_ref"]),
        "read_set": read_set,
        "write_set": write_set,
        "tool_call_budget": int(payload.get("tool_call_budget") or 32),
        "retry_budget": int(payload.get("retry_budget") or 1),
    }
    try:
        office = execute_authorized_agent_office(
            authorization=child_auth,
            routing_decision=office_routing,
            payload={
                "mission_id": mission_id,
                "delegation_id": str(payload.get("delegation_id") or f"delegation:{mission_id}"),
                "goal_id": goal_id,
                "task_type": "BOUNDED_DEVELOPMENT" if write_capable else "READ_ONLY_CODE_ANALYSIS",
                "repository": str(payload.get("repository") or "zenindiones-maker/BR-no-GTA"),
                "branch": str(payload.get("branch") or ""),
                "base_sha": str(payload.get("base_sha") or ""),
                "allowed_agents": [agent_id],
                "allowed_capabilities": [capability_id],
                "allowed_paths": allowed_paths,
                "mission_read_scope": mission_read_scope,
                "mission_write_scope": mission_write_scope,
                "allowed_tools": task["allowed_tools"],
                "allowed_actions": task["allowed_actions"],
                "max_parallelism": 1,
                "time_budget_seconds": int(payload.get("time_budget_seconds") or 600),
                "cost_budget": float(payload.get("cost_budget") or 0),
                "tool_call_budget": int(payload.get("tool_call_budget") or 32),
                "retry_budget": int(payload.get("retry_budget") or 1),
                "expected_outputs": task["expected_outputs"],
                "evidence_requirements": task["evidence_requirements"],
                "input_artifact_refs": task["input_artifact_refs"],
                "acceptance_criteria": task["acceptance_criteria"],
                "tasks": [task],
            },
            repository_root=repository_root,
        )
    finally:
        consume_harness_authorization(child_auth)

    return CapabilityEvidence(
        capability_id=capability_id,
        provider=record.provider,
        status=office.status,
        active=office.active,
        authority=auth.authority,
        authorized_action=auth.authorized_action,
        harness_decision_id=auth.harness_decision_id,
        execution_id=auth.execution_id,
        result=office.result,
        boundary=record.security_boundary,
    )
