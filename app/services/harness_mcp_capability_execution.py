from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.services.harness_capability_service import (
    CapabilityEvidence,
    CapabilityDefinition,
    execute_capability,
)
from app.services.harness_authorization_service import HarnessAuthorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.phone_control_harness_service import execute_authorized_phone_control
from app.services.phone_control_service import PHONE_CAPABILITY_ID, PHONE_EXECUTOR_BINDING
from app.services.agent_office_harness_service import (
    AGENT_OFFICE_CAPABILITY_ID,
    AGENT_OFFICE_EXECUTOR_BINDING,
    execute_authorized_agent_office,
)
from app.services.gta6_fact_check_service import (
    FACT_CHECK_CAPABILITY_ID,
    FACT_CHECK_EXECUTOR_BINDING,
    execute_authorized_gta6_fact_check,
)


SkillExecutor = Callable[[CapabilityDefinition, dict[str, Any]], Any]


MCP_BOUNDED_EXECUTOR_ALLOWLIST = {
    PHONE_CAPABILITY_ID: PHONE_EXECUTOR_BINDING,
    AGENT_OFFICE_CAPABILITY_ID: AGENT_OFFICE_EXECUTOR_BINDING,
    FACT_CHECK_CAPABILITY_ID: FACT_CHECK_EXECUTOR_BINDING,
}


def execute_mcp_capability(
    *,
    routing_decision: HarnessRoutingDecision,
    authorization: HarnessAuthorization,
    payload: dict[str, Any],
    implementation: dict[str, Any],
    skill_executor: SkillExecutor,
) -> CapabilityEvidence:
    """Dispatch only MCP-supported capability classes after Harness authorization.

    Generic SKILL execution keeps the existing bounded skill path. gta6.fact-check
    is explicitly intercepted and dispatched to its deterministic Registry-bound
    executor so a caller-supplied skill executor can never replace the fact-check
    implementation. Side-effecting EXECUTOR capabilities are denied by default
    and must be explicitly allowlisted here.
    """
    capability_id = routing_decision.selected_capability_id
    implementation_type = implementation.get("type")

    if capability_id == FACT_CHECK_CAPABILITY_ID:
        if implementation_type != "SKILL":
            raise PermissionError("gta6.fact-check implementation type mismatch")
        if implementation.get("skill_id") != "gta6-fact-check":
            raise PermissionError("gta6.fact-check skill identity mismatch")
        if routing_decision.selected_executor_binding != FACT_CHECK_EXECUTOR_BINDING:
            raise PermissionError("gta6.fact-check executor binding mismatch")
        if authorization.authorized_action not in {"RESEARCH", "EDITORIAL"}:
            raise PermissionError("gta6.fact-check authorization action mismatch")
        return execute_authorized_gta6_fact_check(
            authorization=authorization,
            routing_decision=routing_decision,
            payload=payload,
        )

    if implementation_type == "SKILL" and implementation.get("skill_id"):
        return execute_capability(
            capability_id=capability_id,
            authorization=authorization,
            payload=payload,
            routing_decision=routing_decision,
            executor=skill_executor,
        )

    expected_binding = MCP_BOUNDED_EXECUTOR_ALLOWLIST.get(capability_id)
    if expected_binding is None:
        raise PermissionError(
            "MCP EXECUTOR capability is not explicitly supported"
        )
    if implementation_type != "EXECUTOR":
        raise PermissionError("MCP bounded executor implementation type mismatch")
    expected_action = (
        "DEVELOPMENT"
        if capability_id == AGENT_OFFICE_CAPABILITY_ID
        else "EXECUTION"
    )
    if authorization.authorized_action != expected_action:
        raise PermissionError(
            f"MCP bounded executor requires {expected_action} authorization"
        )
    if routing_decision.authorized_action != expected_action:
        raise PermissionError("MCP bounded executor routing action mismatch")
    if routing_decision.selected_executor_binding != expected_binding:
        raise PermissionError("MCP bounded executor binding mismatch")

    if capability_id == PHONE_CAPABILITY_ID:
        return execute_authorized_phone_control(
            authorization=authorization,
            routing_decision=routing_decision,
            payload=payload,
        )

    if capability_id == AGENT_OFFICE_CAPABILITY_ID:
        return execute_authorized_agent_office(
            authorization=authorization,
            routing_decision=routing_decision,
            payload=payload,
        )

    raise PermissionError("MCP bounded executor has no registered adapter")
