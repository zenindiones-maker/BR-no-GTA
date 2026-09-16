from __future__ import annotations

from typing import Any

from app.database.channel_branding_standard_repository import (
    REQUIRED_ASSET_TYPES,
    activate_channel_branding_standard,
    get_channel_branding_standard,
)
from app.database.telegram_brand_asset_repository import list_active_brand_assets


def _active_asset_summary() -> list[dict[str, Any]]:
    rows = list_active_brand_assets()
    return [
        {
            "asset_id": int(row["id"]),
            "asset_type": str(row["asset_type"]),
            "telegram_file_unique_id": str(row["telegram_file_unique_id"]),
            "remote_verified": bool(row.get("remote_verified")),
            "active": bool(row.get("active")),
        }
        for row in rows
    ]


def get_channel_branding_readiness() -> dict[str, Any]:
    standard = get_channel_branding_standard()
    assets = _active_asset_summary()
    by_type = {item["asset_type"]: item for item in assets}
    missing = [
        asset_type
        for asset_type in REQUIRED_ASSET_TYPES
        if asset_type not in by_type or not by_type[asset_type]["remote_verified"]
    ]
    return {
        "authority": "deepseek_harness",
        "standard": "BR_NO_GTA_VIDEO_BRANDING_V1",
        "active": bool(standard["active"]),
        "required_asset_types": list(REQUIRED_ASSET_TYPES),
        "ready": not missing,
        "missing_asset_types": missing,
        "assets": assets,
        "activation_source": standard.get("activation_source"),
        "activated_at": standard.get("activated_at"),
        "enforcement": (
            "FAIL_CLOSED_ON_NEW_PRODUCTION"
            if standard["active"]
            else "NOT_ACTIVE_UNTIL_BOTH_ASSETS_REGISTERED"
        ),
    }


def synchronize_channel_branding_standard_after_registration(
    *,
    registration_result: dict[str, Any],
) -> dict[str, Any]:
    readiness = get_channel_branding_readiness()
    if readiness["active"] or not readiness["ready"]:
        return readiness

    asset = registration_result.get("asset") or {}
    standard = activate_channel_branding_standard(
        source="telegram.asset.register",
        provenance={
            "authority": registration_result.get("authority"),
            "routing_id": registration_result.get("routing_id"),
            "authorization_id": registration_result.get("authorization_id"),
            "trigger_asset_id": asset.get("id"),
            "trigger_asset_type": asset.get("asset_type"),
        },
    )
    readiness = get_channel_branding_readiness()
    if not standard["active"] or not readiness["active"] or not readiness["ready"]:
        raise RuntimeError("channel branding standard activation did not persist")
    return readiness


__all__ = [
    "get_channel_branding_readiness",
    "synchronize_channel_branding_standard_after_registration",
]
