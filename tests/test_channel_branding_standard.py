from __future__ import annotations

from app.database.channel_branding_standard_repository import get_channel_branding_standard
from app.services.channel_branding_standard_service import (
    get_channel_branding_readiness,
    synchronize_channel_branding_standard_after_registration,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.production_brand_asset_service import (
    PRODUCTION_BRAND_ASSET_CAPABILITY_ID,
    execute_production_brand_asset_binding_capability,
)
from app.services.telegram_harness_service import register_telegram_brand_asset_under_harness


def _payload(asset_type: str, *, message_id: int, file_id: str, unique_id: str) -> dict:
    if asset_type == "intro":
        return {
            "asset_type": "intro",
            "telegram_file_id": file_id,
            "telegram_file_unique_id": unique_id,
            "media_kind": "video",
            "file_name": "intro.mp4",
            "mime_type": "video/mp4",
            "file_size": 1000,
            "width": 1920,
            "height": 1080,
            "duration_seconds": 5.0,
            "telegram_user_id": 111,
            "telegram_chat_id": 111,
            "telegram_message_id": message_id,
            "telegram_update_id": 1000 + message_id,
            "caption": "essa é a intro oficial do canal",
            "remote_verified": True,
        }
    return {
        "asset_type": "watermark",
        "telegram_file_id": file_id,
        "telegram_file_unique_id": unique_id,
        "media_kind": "photo",
        "file_name": "watermark.png",
        "mime_type": "image/png",
        "file_size": 500,
        "width": 512,
        "height": 512,
        "duration_seconds": None,
        "telegram_user_id": 111,
        "telegram_chat_id": 111,
        "telegram_message_id": message_id,
        "telegram_update_id": 1000 + message_id,
        "caption": "essa é a marca d'água oficial",
        "remote_verified": True,
    }


def test_channel_standard_activates_only_after_both_official_assets_exist():
    first = register_telegram_brand_asset_under_harness(
        _payload("intro", message_id=10, file_id="intro-file", unique_id="intro-unique")
    )
    readiness = synchronize_channel_branding_standard_after_registration(
        registration_result=first,
    )
    assert readiness["active"] is False
    assert readiness["ready"] is False
    assert readiness["missing_asset_types"] == ["watermark"]

    second = register_telegram_brand_asset_under_harness(
        _payload("watermark", message_id=11, file_id="wm-file", unique_id="wm-unique")
    )
    readiness = synchronize_channel_branding_standard_after_registration(
        registration_result=second,
    )

    assert readiness["active"] is True
    assert readiness["ready"] is True
    assert readiness["missing_asset_types"] == []
    assert readiness["required_asset_types"] == ["intro", "watermark"]
    assert readiness["enforcement"] == "FAIL_CLOSED_ON_NEW_PRODUCTION"
    persisted = get_channel_branding_standard()
    assert persisted["active"] is True
    assert persisted["activation_source"] == "telegram.asset.register"


def test_active_channel_standard_binds_exact_intro_and_watermark_into_new_production():
    intro = register_telegram_brand_asset_under_harness(
        _payload("intro", message_id=20, file_id="intro-file", unique_id="intro-unique")
    )
    watermark = register_telegram_brand_asset_under_harness(
        _payload("watermark", message_id=21, file_id="wm-file", unique_id="wm-unique")
    )
    synchronize_channel_branding_standard_after_registration(registration_result=intro)
    synchronize_channel_branding_standard_after_registration(registration_result=watermark)

    capability = GLOBAL_CAPABILITY_REGISTRY.get(PRODUCTION_BRAND_ASSET_CAPABILITY_ID)
    assert capability is not None
    result = execute_production_brand_asset_binding_capability(
        capability,
        content_item_id=999,
    )

    assert result["status"] == "channel_standard_bound"
    assert result["channel_branding_standard_active"] is True
    assert result["asset_count"] == 2
    assert {item["asset_type"] for item in result["brand_assets"]} == {"intro", "watermark"}
    assert all(item["remote_verified"] for item in result["brand_assets"])
