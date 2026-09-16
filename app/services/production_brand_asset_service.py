from __future__ import annotations

from typing import Any

from app.database.channel_branding_standard_repository import (
    REQUIRED_ASSET_TYPES,
    get_channel_branding_standard,
)
from app.database.telegram_brand_asset_repository import list_active_brand_assets
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import (
    HarnessAuthorization,
    validate_harness_authorization,
)
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_routing_policy_service import HarnessRoutingDecision


PRODUCTION_BRAND_ASSET_CAPABILITY_ID = "production.brand-assets.bind"
PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING = (
    "app.services.production_brand_asset_service.execute_production_brand_asset_binding_capability"
)


def _snapshot(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_id": int(record["id"]),
        "asset_type": str(record["asset_type"]),
        "telegram_file_id": str(record["telegram_file_id"]),
        "telegram_file_unique_id": str(record["telegram_file_unique_id"]),
        "media_kind": str(record["media_kind"]),
        "file_name": record.get("file_name"),
        "mime_type": record.get("mime_type"),
        "file_size": record.get("file_size"),
        "width": record.get("width"),
        "height": record.get("height"),
        "duration_seconds": record.get("duration_seconds"),
        "remote_verified": bool(record.get("remote_verified")),
        "source": "telegram",
    }


def execute_production_brand_asset_binding_capability(
    capability: Any,
    *,
    content_item_id: int,
) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != PRODUCTION_BRAND_ASSET_CAPABILITY_ID:
        raise PermissionError("brand asset executor received a different capability")
    if getattr(capability, "executor_binding", None) != PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING:
        raise PermissionError("brand asset executor binding mismatch")
    if not isinstance(content_item_id, int) or isinstance(content_item_id, bool) or content_item_id <= 0:
        raise ValueError("content_item_id must be a positive integer")

    standard = get_channel_branding_standard()
    records = list_active_brand_assets()
    snapshots = [_snapshot(record) for record in records]
    if any(not item["remote_verified"] for item in snapshots):
        raise RuntimeError("active Telegram brand asset is not remotely verified")
    known = {item["asset_type"] for item in snapshots}
    if not known.issubset(set(REQUIRED_ASSET_TYPES)):
        raise RuntimeError("unexpected active brand asset type")

    if standard["active"]:
        missing = [asset_type for asset_type in REQUIRED_ASSET_TYPES if asset_type not in known]
        if missing:
            raise RuntimeError(
                "mandatory BR-no-GTA channel branding is incomplete: "
                + ", ".join(missing)
            )
        if len(snapshots) != len(REQUIRED_ASSET_TYPES):
            raise RuntimeError("mandatory BR-no-GTA channel branding must bind exactly one intro and one watermark")
        status = "channel_standard_bound"
    else:
        status = "bound" if snapshots else "no_active_assets"

    return {
        "content_item_id": content_item_id,
        "brand_assets": snapshots,
        "asset_count": len(snapshots),
        "status": status,
        "channel_branding_standard_active": bool(standard["active"]),
        "required_asset_types": list(REQUIRED_ASSET_TYPES),
    }


def bind_active_brand_assets(
    *,
    content_item_id: int,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision,
    execution_id: str,
) -> dict[str, Any]:
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise PermissionError("brand asset execution_id is required")
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{PRODUCTION_BRAND_ASSET_CAPABILITY_ID}",
        expected_execution_id=execution_id,
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(PRODUCTION_BRAND_ASSET_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("production brand asset capability is not executable")
    if record.executor_binding != PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING:
        raise PermissionError("production brand asset Registry executor mismatch")
    if routing_decision.authorized_action != "EXECUTION":
        raise PermissionError("production brand asset routing action mismatch")
    if routing_decision.selected_capability_id != PRODUCTION_BRAND_ASSET_CAPABILITY_ID:
        raise PermissionError("production brand asset routing capability mismatch")
    if routing_decision.selected_executor_binding != PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING:
        raise PermissionError("production brand asset routing executor mismatch")
    lineage = authorization.lineage
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("production brand asset authorization routing mismatch")
    if lineage.get("capability_id") != PRODUCTION_BRAND_ASSET_CAPABILITY_ID:
        raise PermissionError("production brand asset authorization capability mismatch")
    if lineage.get("selected_executor_binding") != PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING:
        raise PermissionError("production brand asset authorization executor mismatch")
    if lineage.get("content_item_id") != content_item_id:
        raise PermissionError("production brand asset content_item_id lineage mismatch")

    result = execute_production_brand_asset_binding_capability(
        record,
        content_item_id=content_item_id,
    )
    evidence = CapabilityEvidence(
        capability_id=PRODUCTION_BRAND_ASSET_CAPABILITY_ID,
        provider=record.provider,
        status="EXECUTED",
        active=True,
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id,
        result={
            "content_item_id": content_item_id,
            "asset_count": result["asset_count"],
            "asset_ids": [item["asset_id"] for item in result["brand_assets"]],
            "asset_types": [item["asset_type"] for item in result["brand_assets"]],
            "status": result["status"],
            "channel_branding_standard_active": result["channel_branding_standard_active"],
            "required_asset_types": result["required_asset_types"],
        },
        boundary=record.security_boundary,
    )
    canonical = evidence.to_canonical_result(
        authorization_id=authorization.authorization_id,
        routing_id=routing_decision.routing_id,
        executor=PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING,
        operation="bind_active_brand_assets",
    )
    return {
        **result,
        "capability_evidence": evidence.to_dict(),
        "canonical_execution_result": canonical.to_dict(),
    }
