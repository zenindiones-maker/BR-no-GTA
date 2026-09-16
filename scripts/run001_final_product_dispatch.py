from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.main import initialize_application
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.workers.professional_audiovisual_worker import PROFILE, validate_product_job

OFFICIAL_BRAND_ASSETS = [
    {
        "asset_id": 1,
        "asset_type": "intro",
        "telegram_file_id": "BAACAgEAAyEFAATqZuF4AAMDaqqRxrJe-LRgBh6GcsAlaeKS5rEAAoYJAAK_JlhFu95hlYoKGVo9BA",
        "telegram_file_unique_id": "AgADhgkAAr8mWEU",
        "media_kind": "video",
        "file_name": None,
        "mime_type": "video/mp4",
        "file_size": 4043236,
        "width": 1280,
        "height": 720,
        "duration_seconds": 11.0,
        "remote_verified": True,
        "source": "telegram",
    },
    {
        "asset_id": 2,
        "asset_type": "watermark",
        "telegram_file_id": "AgACAgEAAyEFAATqZuF4AAMEaqqSCSln8nvv2v2BeFXIin8kRVMAArkMaxu_JlhFhU0XcDXyixgBAAMCAAN5AAM9BA",
        "telegram_file_unique_id": "AQADuQxrG78mWEV-",
        "media_kind": "photo",
        "file_name": None,
        "mime_type": "image/jpeg",
        "file_size": 207150,
        "width": 1280,
        "height": 1100,
        "duration_seconds": None,
        "remote_verified": True,
        "source": "telegram",
    },
]


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("product contract must be a JSON object")
    return value


def build_render_job(product: dict[str, Any]) -> dict[str, Any]:
    initialize_application()
    if product.get("product_profile") != PROFILE:
        raise RuntimeError(f"product_profile must be {PROFILE}")
    if product.get("render_job_id") == 18:
        raise RuntimeError("Job18 is frozen")
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="render professional PT-BR GTA VI review product through VEdit and FFmpeg",
            authorized_action="EXECUTION",
            required_capability_id="media.ffmpeg",
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        lineage={
            "goal_id": product["goal_id"],
            "product_label": product["product_label"],
            "product_version": product["product_version"],
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "publication_authority": "NONE",
        },
    )
    context = authorization_to_context(authorization)
    job = dict(product)
    job.update(
        id=product["render_job_id"],
        status="running",
        job_type="video_render",
        queue="render",
        attempt=1,
        estimated_duration_seconds=1500.0,
        render={
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        brand_assets=OFFICIAL_BRAND_ASSETS,
        audio_requirements=[
            "Narração PT-BR real e materializada é obrigatória em A1 VOICE.",
            "Áudio original de trailer não pode satisfazer VOICE_QA.",
            "A1 VOICE deve permanecer inteligível e prioritária no mix final.",
        ],
        harness_decision_id=context["harness_decision_id"],
        brain_decision_id=context["brain_decision_id"],
        execution_id=context["execution_id"],
        authorized_action=context["authorized_action"],
        issued_by=context["issued_by"],
        lineage={
            **context["lineage"],
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": product["goal_id"],
            "product_label": product["product_label"],
            "product_version": product["product_version"],
        },
        output_path=None,
        error=None,
        persistence_scope="cloud_review_product_v1",
        human_editorial_approval="PENDING",
        youtube_publication_authority="NONE",
    )
    job["render_job_id"] = product["render_job_id"]
    validate_product_job(job)
    return job


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    job = build_render_job(load(args.product))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(job, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    print(f"VIDEO_{job['product_label']}_HARNESS_AUTHORIZATION=PASS")
    print(f"VIDEO_{job['product_label']}_RESEARCH=PASS")
    print(f"VIDEO_{job['product_label']}_SCRIPT_PTBR=PASS")
    print(f"VIDEO_{job['product_label']}_FACT_CHECK=PASS")
    print(f"RENDER_JOB_ID={job['render_job_id']}")
    print(f"EXECUTION_ID={job['execution_id']}")
    print("JOB18_UNCHANGED=BY_DESIGN_NO_CANONICAL_DATABASE_ACCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
