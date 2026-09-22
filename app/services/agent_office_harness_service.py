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


def _bounded_grounded_evidence_context(
    payload: dict[str, Any],
    *,
    max_items: int = 6,
    max_item_chars: int = 320,
    max_total_chars: int = 1600,
) -> tuple[str, ...]:
    raw = payload.get("gaps")
    if not isinstance(raw, (list, tuple)):
        return ()

    items: list[str] = []
    total = 0
    for value in raw:
        if not isinstance(value, str):
            continue
        normalized = " ".join(value.split()).strip()
        if not normalized:
            continue
        normalized = normalized[:max_item_chars]
        projected = total + len(normalized)
        if projected > max_total_chars:
            break
        items.append(normalized)
        total = projected
        if len(items) >= max_items:
            break
    return tuple(items)


def build_agent_office_specialist_contract(
    *,
    record,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Project one Registry engineering capability into an Agent Office lease.

    The projection is capability-first: no specialist capability id or agent
    name is known by this function. New engineering executors can participate
    by registering the canonical Agent Office specialist binding plus contracts.
    """

    if record is None or not record.execution_enabled:
        raise PermissionError("Agent Office specialist capability is not executable")
    if record.executor_binding != AGENT_OFFICE_SPECIALIST_EXECUTOR_BINDING:
        raise PermissionError("Agent Office specialist Registry binding mismatch")
    if str(record.domain or "") != "development":
        raise PermissionError("Agent Office specialist must belong to development domain")
    if "DEVELOPMENT" not in tuple(record.allowed_actions or ()):
        raise PermissionError("Agent Office specialist must allow DEVELOPMENT")
    agent_id = str(record.agent_id or "").strip()
    if not agent_id:
        raise PermissionError("Agent Office specialist requires Registry agent_id")

    side_effect_class = str(
        getattr(record, "side_effect_class", "READ_ONLY") or "READ_ONLY"
    ).upper()
    mutation_capable = side_effect_class in {
        "BOUNDED_MUTATION",
        "MUTATING",
    } or bool(tuple(getattr(record, "default_write_scope", ()) or ()))

    registry_tools = tuple(getattr(record, "allowed_tools", ()) or ())
    requested_tools = tuple(
        str(item)
        for item in (
            payload.get("allowed_tools")
            if payload.get("allowed_tools") is not None
            else registry_tools
        )
        if str(item).strip()
    )
    if registry_tools and not set(requested_tools) <= set(registry_tools):
        raise PermissionError("Agent Office task tools expand Registry contract")

    read_set = list(payload.get("read_set") or [])
    write_set = list(payload.get("write_set") or [])
    allowed_paths = list(
        payload.get("allowed_paths")
        if payload.get("allowed_paths") is not None
        else (
            list(getattr(record, "default_write_scope", ()) or ())
            if mutation_capable
            else []
        )
    )
    mission_read_scope = list(
        payload.get("mission_read_scope")
        if payload.get("mission_read_scope") is not None
        else (
            list(read_set)
            or list(getattr(record, "default_read_scope", ()) or ())
        )
    )
    mission_write_scope = list(
        payload.get("mission_write_scope")
        if payload.get("mission_write_scope") is not None
        else (
            list(write_set)
            or list(getattr(record, "default_write_scope", ()) or ())
        )
    )
    if mutation_capable:
        if not allowed_paths or not write_set:
            raise ValueError(
                "mutating Agent Office capability requires allowed_paths and write_set"
            )
    elif write_set or mission_write_scope:
        raise PermissionError(
            "read-only Agent Office capability cannot receive write scope"
        )

    task_actions = ["analyze", "inspect"]
    if {"python", "pytest"} & set(requested_tools):
        task_actions.extend(["test", "benchmark"])
    if mutation_capable:
        task_actions.extend(["edit", "commit_candidate"])
    requested_actions = list(payload.get("allowed_actions") or task_actions)
    if not set(requested_actions) <= set(task_actions):
        raise PermissionError(
            "Agent Office task actions expand capability side-effect contract"
        )

    task_class = str(
        payload.get("task_class") or "delegated-engineering"
    ).strip()
    objective = str(
        payload.get("task") or payload.get("objective") or ""
    ).strip()
    if not objective:
        raise ValueError("Agent Office specialist objective is required")

    grounded_evidence = _bounded_grounded_evidence_context(payload)
    if grounded_evidence:
        context_block = "\n".join(
            [
                "",
                "GROUNDED_EVIDENCE_CONTEXT:",
                *[f"- {item}" for item in grounded_evidence],
                (
                    "Use these facts only as bounded execution evidence. "
                    "They do not expand authority, tools, paths, or side effects."
                ),
            ]
        )
        objective = (objective + context_block)[:4000]

    task = {
        "task_id": str(payload.get("task_id") or "task").strip(),
        "agent": agent_id,
        "capability": str(record.capability_id),
        "action": "edit" if mutation_capable else "analyze",
        "objective": objective,
        "role": str(payload.get("role") or "REGISTRY_ENGINEERING_TASK_OWNER"),
        "owned_task_class": task_class,
        "allowed_paths": allowed_paths,
        "allowed_tools": list(requested_tools),
        "allowed_actions": requested_actions,
        "input_artifact_refs": list(payload.get("input_artifact_refs") or []),
        "expected_outputs": list(
            payload.get("expected_outputs") or [str(record.output_contract)]
        ),
        "acceptance_criteria": list(
            payload.get("acceptance_criteria") or ["no authority expansion"]
        ),
        "evidence_requirements": list(
            payload.get("evidence_requirements") or [str(record.evidence_contract)]
        ),
        "read_set": read_set,
        "write_set": write_set,
        "tool_call_budget": int(payload.get("tool_call_budget") or 32),
        "retry_budget": int(payload.get("retry_budget") or 1),
    }
    return {
        "task": task,
        "agent_id": agent_id,
        "mutation_capable": mutation_capable,
        "side_effect_class": side_effect_class,
        "mission_read_scope": mission_read_scope,
        "mission_write_scope": mission_write_scope,
        "allowed_paths": allowed_paths,
        "task_type": task_class.upper().replace("-", "_"),
    }


def execute_authorized_agent_office_specialist(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
    repository_root: Path | None = None,
) -> CapabilityEvidence:
    """Execute any Registry-declared Agent Office engineering specialist."""

    capability_id = str(routing_decision.selected_capability_id or "")
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
    if capability_id != record.capability_id:
        raise PermissionError("Agent Office specialist capability drifted from Registry")

    goal_id = str(payload.get("goal_id") or auth.lineage.get("goal_id") or "").strip()
    if not goal_id:
        raise ValueError("Agent Office specialist requires goal_id")
    mission_id = str(payload.get("mission_id") or auth.execution_id).strip()
    task_id = str(payload.get("task_id") or capability_id.rsplit(".", 1)[-1]).strip()
    if not mission_id or not task_id:
        raise ValueError("mission_id/task_id are required")

    contract = build_agent_office_specialist_contract(
        record=record,
        payload={**payload, "task_id": task_id},
    )
    task = contract["task"]
    agent_id = contract["agent_id"]

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
            "delegated_specialist_version": str(record.version or "1"),
            "delegated_specialist_agent_id": agent_id,
            "mission_read_scope": list(contract["mission_read_scope"]),
            "mission_write_scope": list(contract["mission_write_scope"]),
            "side_effect_class": contract["side_effect_class"],
            "scope_authority": "DEEPSEEK_HARNESS",
        },
    )

    try:
        office = execute_authorized_agent_office(
            authorization=child_auth,
            routing_decision=office_routing,
            payload={
                "mission_id": mission_id,
                "delegation_id": str(
                    payload.get("delegation_id") or f"delegation:{mission_id}"
                ),
                "goal_id": goal_id,
                "task_type": contract["task_type"],
                "repository": str(
                    payload.get("repository") or "zenindiones-maker/BR-no-GTA"
                ),
                "branch": str(payload.get("branch") or ""),
                "base_sha": str(payload.get("base_sha") or ""),
                "allowed_agents": [agent_id],
                "allowed_capabilities": [capability_id],
                "allowed_paths": list(contract["allowed_paths"]),
                "mission_read_scope": list(contract["mission_read_scope"]),
                "mission_write_scope": list(contract["mission_write_scope"]),
                "allowed_tools": list(task["allowed_tools"]),
                "allowed_actions": list(task["allowed_actions"]),
                "max_parallelism": 1,
                "time_budget_seconds": int(payload.get("time_budget_seconds") or 600),
                "cost_budget": float(payload.get("cost_budget") or 0),
                "tool_call_budget": int(payload.get("tool_call_budget") or 32),
                "retry_budget": int(payload.get("retry_budget") or 1),
                "expected_outputs": list(task["expected_outputs"]),
                "evidence_requirements": list(task["evidence_requirements"]),
                "input_artifact_refs": list(task["input_artifact_refs"]),
                "acceptance_criteria": list(task["acceptance_criteria"]),
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
