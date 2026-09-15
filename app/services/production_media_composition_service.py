from __future__ import annotations

from typing import Any

from app.database.production_plan_repository import (
    get_production_plan_by_content_item_id,
    update_production_plan,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.production_media_bridge import bind_selected_segments


PRODUCTION_MEDIA_CAPABILITY_ID = "production.media.bind-selected-segments"
PRODUCTION_MEDIA_EXECUTOR_BINDING = (
    "app.services.production_media_composition_service."
    "execute_production_media_binding_capability"
)


def _load_plan(content_item_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(content_item_id, int) or isinstance(content_item_id, bool) or content_item_id <= 0:
        raise ValueError("content_item_id deve ser um inteiro positivo.")
    production_record = get_production_plan_by_content_item_id(content_item_id)
    if production_record is None:
        raise RuntimeError(f"ProductionPlan não encontrado para content_item_id={content_item_id}.")
    production_plan = production_record.get("production_plan")
    if not isinstance(production_plan, dict):
        raise RuntimeError("Registro persistido não contém ProductionPlan válido.")
    if production_plan.get("content_item_id") != content_item_id:
        raise RuntimeError("ProductionPlan possui content_item_id incompatível.")
    return production_record, production_plan


def _validate_segment_ids(segment_ids: list[int]) -> None:
    if not isinstance(segment_ids, list) or not segment_ids:
        raise ValueError("segment_ids deve ser uma lista não vazia.")
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0 for value in segment_ids):
        raise ValueError("Todos os segment_ids devem ser inteiros positivos.")


def _validate_boundary(
    *,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    execution_id: str,
    production_plan: dict[str, Any],
) -> tuple[HarnessAuthorization, Any]:
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise PermissionError("production media execution_id is required")
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{PRODUCTION_MEDIA_CAPABILITY_ID}",
        expected_execution_id=execution_id,
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(PRODUCTION_MEDIA_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("production media capability is not executable")
    if record.executor_binding != PRODUCTION_MEDIA_EXECUTOR_BINDING:
        raise PermissionError("production media Registry executor mismatch")
    if routing_decision.authorized_action != "EXECUTION":
        raise PermissionError("production media routing action mismatch")
    if routing_decision.selected_capability_id != PRODUCTION_MEDIA_CAPABILITY_ID:
        raise PermissionError("production media routing capability mismatch")
    if routing_decision.selected_executor_binding != PRODUCTION_MEDIA_EXECUTOR_BINDING:
        raise PermissionError("production media routing executor mismatch")

    lineage = authorization.lineage
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("production media authorization routing mismatch")
    if lineage.get("capability_id") != PRODUCTION_MEDIA_CAPABILITY_ID:
        raise PermissionError("production media authorization capability mismatch")
    if lineage.get("selected_executor_binding") != PRODUCTION_MEDIA_EXECUTOR_BINDING:
        raise PermissionError("production media authorization executor mismatch")
    for key in ("content_item_id", "script_id", "idea_id"):
        if lineage.get(key) != production_plan.get(key):
            raise PermissionError(f"production media authorization {key} lineage mismatch")
    return authorization, record


def execute_production_media_binding_capability(
    capability: Any,
    *,
    production_plan: dict[str, Any],
    segment_ids: list[int],
) -> dict[str, Any]:
    """Bounded Media executor. Direct callers cannot substitute capability/executor metadata."""
    if getattr(capability, "capability_id", None) != PRODUCTION_MEDIA_CAPABILITY_ID:
        raise PermissionError("production media executor received a different capability")
    if getattr(capability, "executor_binding", None) != PRODUCTION_MEDIA_EXECUTOR_BINDING:
        raise PermissionError("production media executor binding mismatch")
    return bind_selected_segments(production_plan, segment_ids)


def compose_and_persist_production_media(
    *,
    content_item_id: int,
    segment_ids: list[int],
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    execution_id: str,
) -> dict[str, Any]:
    """Harness-authorized Production -> Media binding boundary; fail closed before bind."""
    _validate_segment_ids(segment_ids)
    production_record, production_plan = _load_plan(content_item_id)
    authorization, record = _validate_boundary(
        authorization=authorization,
        routing_decision=routing_decision,
        execution_id=execution_id,
        production_plan=production_plan,
    )

    # The only call to bind_selected_segments is behind the complete boundary.
    composed_plan = execute_production_media_binding_capability(
        record,
        production_plan=production_plan,
        segment_ids=segment_ids,
    )
    persisted = update_production_plan(content_item_id=content_item_id, production_plan=composed_plan)
    if not persisted:
        raise RuntimeError("ProductionPlan não foi atualizado.")

    persisted_record, persisted_plan = _load_plan(content_item_id)
    scenes = persisted_plan.get("scenes")
    if not isinstance(scenes, list):
        raise RuntimeError("ProductionPlan persistido não possui cenas válidas.")
    persisted_segment_ids = [scene.get("segment_id") for scene in scenes if isinstance(scene, dict)]
    if persisted_segment_ids != segment_ids:
        raise RuntimeError("segment_ids persistidos não correspondem à composição solicitada.")

    result = {
        "content_item_id": content_item_id,
        "production_plan_id": persisted_record["id"],
        "segment_ids": persisted_segment_ids,
        "scene_count": len(scenes),
        "status": "composed",
        "production_plan": persisted_plan,
    }
    evidence = CapabilityEvidence(
        capability_id=PRODUCTION_MEDIA_CAPABILITY_ID,
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
    canonical = evidence.to_canonical_result(
        authorization_id=authorization.authorization_id,
        routing_id=routing_decision.routing_id,
        executor=PRODUCTION_MEDIA_EXECUTOR_BINDING,
        operation="bind_selected_segments",
    )
    return {
        **result,
        "capability_evidence": evidence.to_dict(),
        "canonical_execution_result": canonical.to_dict(),
    }
