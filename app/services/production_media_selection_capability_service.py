from __future__ import annotations

from typing import Any

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.production_media_selection_service import select_production_media


PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID = "production.media.select-segments"
PRODUCTION_MEDIA_SELECTION_EXECUTOR_BINDING = (
    "app.services.production_media_selection_capability_service."
    "execute_production_media_selection_capability"
)


def execute_production_media_selection_capability(
    capability: Any,
    *,
    content_item_id: int,
    knowledge_id: int,
) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID:
        raise PermissionError("production media selection executor received a different capability")
    if getattr(capability, "executor_binding", None) != PRODUCTION_MEDIA_SELECTION_EXECUTOR_BINDING:
        raise PermissionError("production media selection executor binding mismatch")
    return select_production_media(
        content_item_id=content_item_id,
        knowledge_id=knowledge_id,
    )


def select_authorized_production_media(
    *,
    content_item_id: int,
    knowledge_id: int,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    execution_id: str,
) -> dict[str, Any]:
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise PermissionError("production media selection execution_id is required")
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID}",
        expected_execution_id=execution_id,
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("production media selection capability is not executable")
    if record.executor_binding != PRODUCTION_MEDIA_SELECTION_EXECUTOR_BINDING:
        raise PermissionError("production media selection Registry executor mismatch")
    if routing_decision.authorized_action != "EXECUTION":
        raise PermissionError("production media selection routing action mismatch")
    if routing_decision.selected_capability_id != PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID:
        raise PermissionError("production media selection routing capability mismatch")
    if routing_decision.selected_executor_binding != PRODUCTION_MEDIA_SELECTION_EXECUTOR_BINDING:
        raise PermissionError("production media selection routing executor mismatch")

    lineage = authorization.lineage
    expected = {
        "routing_id": routing_decision.routing_id,
        "capability_id": PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID,
        "selected_executor_binding": PRODUCTION_MEDIA_SELECTION_EXECUTOR_BINDING,
        "content_item_id": content_item_id,
        "knowledge_id": knowledge_id,
    }
    for key, value in expected.items():
        if lineage.get(key) != value:
            raise PermissionError(f"production media selection authorization {key} lineage mismatch")

    result = execute_production_media_selection_capability(
        record,
        content_item_id=content_item_id,
        knowledge_id=knowledge_id,
    )
    evidence = CapabilityEvidence(
        capability_id=PRODUCTION_MEDIA_SELECTION_CAPABILITY_ID,
        provider=record.provider,
        status="EXECUTED",
        active=True,
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id,
        result={
            "content_item_id": content_item_id,
            "knowledge_id": knowledge_id,
            "segment_ids": list(result["segment_ids"]),
            "scene_count": result["scene_count"],
            "status": result["status"],
        },
        boundary=record.security_boundary,
    )
    canonical = evidence.to_canonical_result(
        authorization_id=authorization.authorization_id,
        routing_id=routing_decision.routing_id,
        executor=PRODUCTION_MEDIA_SELECTION_EXECUTOR_BINDING,
        operation="select_production_media",
    )
    return {
        **result,
        "capability_evidence": evidence.to_dict(),
        "canonical_execution_result": canonical.to_dict(),
    }
