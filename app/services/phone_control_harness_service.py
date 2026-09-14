from __future__ import annotations

from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import (
    CapabilityEvidence,
    CapabilityExecutionBlocked,
)
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.phone_control_service import (
    PHONE_CAPABILITY_ID,
    PHONE_EXECUTOR_BINDING,
    execute_phone_control_capability,
)


def _validate_phone_boundary(
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
) -> HarnessAuthorization:
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{PHONE_CAPABILITY_ID}",
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(PHONE_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("phone.control is not executable")
    if record.executor_binding != PHONE_EXECUTOR_BINDING:
        raise PermissionError("phone.control Registry executor mismatch")
    if routing_decision.authorized_action != "EXECUTION":
        raise PermissionError("phone.control routing action mismatch")
    if routing_decision.selected_capability_id != PHONE_CAPABILITY_ID:
        raise PermissionError("phone.control routing capability mismatch")
    if routing_decision.selected_executor_binding != PHONE_EXECUTOR_BINDING:
        raise PermissionError("phone.control routing executor mismatch")

    lineage = authorization.lineage
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("phone.control authorization routing mismatch")
    if lineage.get("capability_id") != PHONE_CAPABILITY_ID:
        raise PermissionError("phone.control authorization capability mismatch")
    if lineage.get("selected_executor_binding") != PHONE_EXECUTOR_BINDING:
        raise PermissionError("phone.control authorization executor mismatch")
    return authorization


def execute_authorized_phone_control(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    payload: dict[str, Any],
) -> CapabilityEvidence:
    """Execute one phone.control operation after persisted Harness authorization."""
    authorization = _validate_phone_boundary(authorization, routing_decision)
    record = GLOBAL_CAPABILITY_REGISTRY.get(PHONE_CAPABILITY_ID)
    assert record is not None

    try:
        result = execute_phone_control_capability(record, payload)
    except CapabilityExecutionBlocked as exc:
        return CapabilityEvidence(
            capability_id=PHONE_CAPABILITY_ID,
            provider=record.provider,
            status="BLOCKED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={"stage": exc.stage, "error": exc.safe_message},
            boundary=exc.boundary,
        )
    except Exception:
        return CapabilityEvidence(
            capability_id=PHONE_CAPABILITY_ID,
            provider=record.provider,
            status="FAILED",
            active=False,
            authority=authorization.authority,
            authorized_action=authorization.authorized_action,
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            result={"error": "phone.control executor failed"},
            boundary="phone.control failed; no fallback executed",
        )

    return CapabilityEvidence(
        capability_id=PHONE_CAPABILITY_ID,
        provider=record.provider,
        status="EXECUTED",
        active=True,
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id,
        result=result,
        boundary=record.security_boundary,
    )
