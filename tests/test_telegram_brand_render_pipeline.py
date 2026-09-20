from __future__ import annotations

from pathlib import Path

from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.production_brand_asset_service import (
    PRODUCTION_BRAND_ASSET_CAPABILITY_ID,
    PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING,
    bind_active_brand_assets,
)
from app.services.render_job_service import create_render_job
from app.services.telegram_brand_asset_materializer import materialize_telegram_brand_assets
from app.services.telegram_harness_service import register_telegram_brand_asset_under_harness
from app.services.video_execution_service import create_video_execution_spec
from app.workers.brand_asset_worker import _build_ffmpeg_command
from app.services.visual_branding_policy import watermark_geometry


def _watermark_payload():
    return {
        "asset_type": "watermark",
        "telegram_file_id": "tg-watermark-file",
        "telegram_file_unique_id": "tg-watermark-unique",
        "media_kind": "photo",
        "file_name": "watermark.png",
        "mime_type": "image/png",
        "file_size": 4,
        "width": 512,
        "height": 512,
        "duration_seconds": None,
        "telegram_user_id": 111,
        "telegram_chat_id": 111,
        "telegram_message_id": 22,
        "telegram_update_id": 122,
        "caption": "essa é a marca d'água oficial",
        "remote_verified": True,
    }


def test_active_asset_binding_is_harness_governed_and_snapshot_contains_no_token():
    registered = register_telegram_brand_asset_under_harness(_watermark_payload())
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="production branding bind active intro watermark assets",
            authorized_action="EXECUTION",
            domain="production-branding",
            required_capability_id=PRODUCTION_BRAND_ASSET_CAPABILITY_ID,
            required_policy_tags=("production", "branding", "binding"),
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    execution_id = "brand-render-test"
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{PRODUCTION_BRAND_ASSET_CAPABILITY_ID}",
        execution_id=execution_id,
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": PRODUCTION_BRAND_ASSET_CAPABILITY_ID,
            "selected_executor_binding": PRODUCTION_BRAND_ASSET_EXECUTOR_BINDING,
            "content_item_id": 99,
        },
    )

    result = bind_active_brand_assets(
        content_item_id=99,
        authorization=authorization,
        routing_decision=routing,
        execution_id=execution_id,
    )

    assert result["status"] == "bound"
    assert result["asset_count"] == 1
    snapshot = result["brand_assets"][0]
    assert snapshot["asset_id"] == registered["asset"]["id"]
    assert snapshot["asset_type"] == "watermark"
    assert snapshot["telegram_file_id"] == "tg-watermark-file"
    assert snapshot["remote_verified"] is True
    assert all("token" not in key.casefold() for key in snapshot)
    canonical = result["canonical_execution_result"]
    assert canonical["authority"] == "deepseek_harness"
    assert canonical["capability_id"] == PRODUCTION_BRAND_ASSET_CAPABILITY_ID
    assert canonical["success"] is True


def test_brand_snapshot_survives_video_execution_and_render_job_contract():
    brand_assets = [
        {
            "asset_id": 7,
            "asset_type": "watermark",
            "telegram_file_id": "file-id",
            "telegram_file_unique_id": "unique-id",
            "media_kind": "photo",
            "file_name": "wm.png",
            "mime_type": "image/png",
            "file_size": 100,
            "remote_verified": True,
            "source": "telegram",
        }
    ]
    video_spec = {
        "content_item_id": 1,
        "script_id": 2,
        "idea_id": 3,
        "objective": "test",
        "format": "longform",
        "estimated_duration_seconds": 45.0,
        "scenes": [
            {
                "order": 1,
                "narrative_block": "opening",
                "narration": "hello",
                "visual_type": "clip",
                "visual_description": "clip",
                "duration_seconds": 45.0,
                "requirements": [],
            }
        ],
        "audio_requirements": [],
        "visual_requirements": [],
        "brand_assets": brand_assets,
    }

    execution = create_video_execution_spec(video_spec)
    render_job = create_render_job(execution, video_id=5)

    assert execution["brand_assets"] == brand_assets
    assert render_job["brand_assets"] == brand_assets
    assert render_job["brand_assets"] is not brand_assets


def test_cloud_materializer_resolves_getfile_downloads_and_emits_sanitized_hash_evidence(tmp_path):
    calls = []

    def fake_api(token, method, payload):
        calls.append((token, method, payload))
        return {"file_path": "photos/watermark.png"}

    def fake_download(token, remote_path, destination):
        assert token == "secret-token"
        assert remote_path == "photos/watermark.png"
        destination.write_bytes(b"data")

    def fake_probe(path: Path):
        assert path.read_bytes() == b"data"
        return {
            "streams": [{"codec_type": "video", "width": 512, "height": 512}],
            "format": {},
        }

    job = {
        "brand_assets": [
            {
                "asset_id": 7,
                "asset_type": "watermark",
                "telegram_file_id": "file-id",
                "telegram_file_unique_id": "unique-id",
                "media_kind": "photo",
                "file_name": "watermark.png",
                "mime_type": "image/png",
                "file_size": 4,
                "remote_verified": True,
            }
        ]
    }

    hydrated, evidence = materialize_telegram_brand_assets(
        job,
        tmp_path,
        token="secret-token",
        api_call=fake_api,
        downloader=fake_download,
        probe=fake_probe,
    )

    assert calls == [("secret-token", "getFile", {"file_id": "file-id"})]
    assert Path(hydrated[0]["media_path"]).is_file()
    assert evidence[0]["asset_type"] == "watermark"
    assert evidence[0]["size_bytes"] == 4
    assert evidence[0]["downloaded_in_cloud"] is True
    assert len(evidence[0]["sha256"]) == 64
    rendered = repr(evidence)
    assert "secret-token" not in rendered
    assert "file-id" not in rendered


def test_brand_ffmpeg_stage_prepends_complete_intro_then_watermarks_content_without_token():
    command, evidence = _build_ffmpeg_command(
        base=Path("base.mp4"),
        output=Path("final.mp4"),
        assets=[
            {
                "asset_id": 1,
                "asset_type": "intro",
                "media_path": "/runner/intro.mp4",
                "duration_seconds": 5.0,
                "has_video": True,
                "has_audio": True,
                "av_sync_verified": True,
            },
            {
                "asset_id": 2,
                "asset_type": "watermark",
                "media_path": "/runner/watermark.png",
                "duration_seconds": None,
                "has_audio": False,
            },
        ],
        width=1920,
        height=1080,
        fps=30.0,
        expected_duration=1500.0,
    )
    joined = " ".join(command)
    assert "intro.mp4" in joined
    assert "watermark.png" in joined
    assert "concat=n=2:v=1:a=1" in joined
    assert "trim=" not in joined
    assert "atrim=" not in joined
    assert "setpts=PTS-STARTPTS" in joined
    assert "volume=0" not in joined
    assert "amix=" not in joined
    assert "overlay=x=W-w-" in joined
    assert "-t" not in command
    assert evidence["intro_duration_seconds"] == 5.0
    assert evidence["content_expected_duration_seconds"] == 1500.0
    assert evidence["final_expected_duration_seconds"] == 1505.0
    assert evidence["watermark_start_seconds"] == 5.0
    assert evidence["watermark_scale"] == 0.16
    assert evidence["watermark_position"] == "BOTTOM_RIGHT"
    assert evidence["watermark_applied_to"] == "CONTENT_ONLY"
    assert "bot" not in joined.casefold()
    assert "token" not in joined.casefold()


def test_watermark_geometry_matches_existing_bottom_right_contract():
    geometry = watermark_geometry(
        canvas_width=1920,
        canvas_height=1080,
        source_width=1280,
        source_height=1100,
    )
    assert geometry["target_width"] == 307
    assert geometry["position"] == "BOTTOM_RIGHT"
    assert geometry["opacity"] == 0.78
    assert geometry["x_offset_from_center"] > 0
    assert geometry["y_offset_from_center"] > 0
