from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.agent_office.contracts import AgentOfficeExecutionSpec, AgentOfficeTask
from app.services.agent_office.service import AgentOfficeService
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_routing_policy_service import HarnessRoutingDecision


AGENT_OFFICE_CAPABILITY_ID = "agent-office.execute"
AGENT_OFFICE_EXECUTOR_BINDING = (
    "app.services.agent_office_harness_service.execute_agent_office_capability"
)
DEFAULT_FORBIDDEN_ACTIONS = (
    "youtube_publish",
    "autonomous_schedule",
    "secret_access",
    "policy_mutation",
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
