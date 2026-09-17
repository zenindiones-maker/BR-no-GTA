from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.main import initialize_application
from app.services.edit_plan_service import EditAudio, EditClip, EditPlan, EditQA, EditTrack
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.workers.audiovisual_worker import validate_job
from scripts.run001_final_product_dispatch import OFFICIAL_BRAND_ASSETS


SCHEMA = "run001-e2e-canary-request/v1"
RENDER_WORKFLOW = ".github/workflows/render-worker.yml"
MIN_DURATION_SECONDS = 30.0
MAX_DURATION_SECONDS = 60.0
FORBIDDEN_RENDER_JOB_IDS = {18, 20}


class E2ECanaryControllerError(ValueError):
    pass


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise E2ECanaryControllerError("canary request must be a JSON object")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise E2ECanaryControllerError(f"{label} must be a positive integer")
    return value


def _required_text(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise E2ECanaryControllerError(f"{label} is required")
    return normalized


def validate_request(request: dict[str, Any]) -> dict[str, Any]:
    if request.get("schema") != SCHEMA:
        raise E2ECanaryControllerError(f"schema must be {SCHEMA}")
    duration = float(request.get("estimated_duration_seconds") or 0.0)
    if not MIN_DURATION_SECONDS <= duration <= MAX_DURATION_SECONDS:
        raise E2ECanaryControllerError("canary duration must be between 30 and 60 seconds")
    for key in ("render_job_id", "video_id", "content_item_id", "script_id", "idea_id"):
        _positive_int(request.get(key), key)
    if request["render_job_id"] in FORBIDDEN_RENDER_JOB_IDS:
        raise E2ECanaryControllerError("Job18 is frozen and Job20 cannot be reused as final")
    if request.get("review_only") is not True:
        raise E2ECanaryControllerError("canary must be review_only")
    if request.get("youtube_publication") is not False:
        raise E2ECanaryControllerError("YouTube publication is forbidden for this canary")
    source_url = _required_text(request.get("source_url"), "source_url")
    if not source_url.startswith("https://www.youtube.com/watch?v="):
        raise E2ECanaryControllerError("source_url must be an explicit YouTube watch URL")
    source_start = float(request.get("source_start_seconds") or 0.0)
    if source_start < 0:
        raise E2ECanaryControllerError("source_start_seconds must be non-negative")
    request = dict(request)
    request["estimated_duration_seconds"] = duration
    request["source_start_seconds"] = source_start
    request["goal_id"] = _required_text(request.get("goal_id"), "goal_id")
    request["execution_id"] = _required_text(request.get("execution_id"), "execution_id")
    return request


def _build_edit_plan(request: dict[str, Any], asset_ref: str) -> EditPlan:
    duration = request["estimated_duration_seconds"]
    source_start = request["source_start_seconds"]
    return EditPlan(
        version="1",
        content_item_id=request["content_item_id"],
        script_id=request["script_id"],
        title="RUN-001 E2E Acceptance Canary",
        objective="Prove the official cloud render, QA, branding and Telegram review path.",
        format="video",
        duration_seconds=duration,
        tracks=(
            EditTrack(
                name="V1 MAIN",
                kind="video",
                clips=(
                    EditClip(
                        segment_id=1,
                        media_path=asset_ref,
                        track="V1 MAIN",
                        start_seconds=0.0,
                        source_start_seconds=source_start,
                        duration_seconds=duration,
                        role="acceptance_canary",
                        fit="cover",
                    ),
                ),
            ),
        ),
        audio=(
            EditAudio(
                media_path=asset_ref,
                track="A1",
                start_seconds=0.0,
                source_start_seconds=source_start,
                duration_seconds=duration,
                volume=1.0,
                fade_in_seconds=0.0,
                fade_out_seconds=0.0,
            ),
        ),
        transitions=(),
        effects=(),
        qa=EditQA(
            min_duration_seconds=MIN_DURATION_SECONDS,
            max_duration_seconds=MAX_DURATION_SECONDS,
            require_audio=True,
            require_video=True,
            require_valid_container=True,
            require_no_missing_media=True,
        ),
        metadata={
            "controller": "run001-e2e-canary",
            "review_only": True,
            "publication_authority": "NONE",
            "render_worker": RENDER_WORKFLOW,
        },
    )


def build_canary_bundle(request: dict[str, Any]) -> dict[str, dict[str, Any]]:
    request = validate_request(request)
    initialize_application()
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="render RUN-001 short E2E acceptance canary through official VEdit/FFmpeg worker",
            authorized_action="EXECUTION",
            required_capability_id="media.ffmpeg",
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    if routing.selected_capability_id != "media.ffmpeg":
        raise E2ECanaryControllerError("Harness did not route the official media.ffmpeg capability")
    if not routing.selected_executor_binding:
        raise E2ECanaryControllerError("Harness routing returned no executor binding")

    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        execution_id=request["execution_id"],
        lineage={
            "goal_id": request["goal_id"],
            "render_job_id": request["render_job_id"],
            "video_id": request["video_id"],
            "content_item_id": request["content_item_id"],
            "script_id": request["script_id"],
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "review_only": True,
            "publication_authority": "NONE",
        },
    )
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject="action:EXECUTION",
        expected_execution_id=request["execution_id"],
    )
    context = authorization_to_context(authorization)

    asset_ref = f"remote://media-worker/run001-e2e-canary/{request['video_id']}"
    duration = request["estimated_duration_seconds"]
    source_start = request["source_start_seconds"]
    source_end = source_start + duration
    scene = {
        "segment_id": 1,
        "content_unit_id": 1,
        "asset_ref": asset_ref,
        "source_url": request["source_url"],
        "source_start_seconds": source_start,
        "source_end_seconds": source_end,
        "duration_seconds": duration,
        "role": "acceptance_canary",
        "narrative_block": "acceptance_canary",
        "visual_type": "official_game_trailer",
        "narration": "Canário operacional do pipeline oficial BR no GTA 6.",
    }
    audio = {
        "type": "voiceover",
        "role": "acceptance_canary_audio",
        "asset_ref": asset_ref,
        "source_url": request["source_url"],
        "source_start_seconds": source_start,
        "source_end_seconds": source_end,
        "duration_seconds": duration,
        "start_seconds": 0.0,
        "volume": 1.0,
    }
    edit_plan = _build_edit_plan(request, asset_ref)
    job: dict[str, Any] = {
        "id": request["render_job_id"],
        "render_job_id": request["render_job_id"],
        "video_id": request["video_id"],
        "content_item_id": request["content_item_id"],
        "script_id": request["script_id"],
        "idea_id": request["idea_id"],
        "goal_id": request["goal_id"],
        "brain_decision_id": context["brain_decision_id"],
        "harness_decision_id": context["harness_decision_id"],
        "execution_id": context["execution_id"],
        "authorized_action": context["authorized_action"],
        "issued_by": context["issued_by"],
        "status": "running",
        "job_type": "video_render",
        "queue": "render",
        "attempt": 1,
        "title": "RUN-001 E2E Acceptance Canary",
        "objective": "Official render-worker acceptance canary for human Telegram review.",
        "format": "video",
        "estimated_duration_seconds": duration,
        "scenes": [scene],
        "audio_requirements": [audio],
        "edit_plan": edit_plan.to_dict(),
        "render": {
            "resolution": "1920x1080",
            "fps": 30,
            "aspect_ratio": "16:9",
            "container": "mp4",
            "video_codec": "h264",
            "audio_codec": "aac",
        },
        "brand_assets": OFFICIAL_BRAND_ASSETS,
        "lineage": {
            "goal_id": request["goal_id"],
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "controller": "run001-e2e-canary",
        },
        "review_only": True,
        "human_review_state": "NOT_DELIVERED",
        "youtube_publication": False,
        "youtube_publication_authority": "NONE",
        "persistence_scope": "run001_e2e_canary_v1",
        "output_path": None,
        "error": None,
    }
    validate_job(job)

    goal = {
        "goal_id": request["goal_id"],
        "stage": "EXECUTION",
        "status": "AUTHORIZED",
        "render_job_id": request["render_job_id"],
        "video_id": request["video_id"],
        "review_only": True,
        "youtube_publication": False,
    }
    video = {
        "video_id": request["video_id"],
        "content_item_id": request["content_item_id"],
        "script_id": request["script_id"],
        "goal_id": request["goal_id"],
        "render_job_id": request["render_job_id"],
        "execution_id": request["execution_id"],
        "status": "RENDER_DISPATCH_PENDING",
    }
    content_item = {
        "content_item_id": request["content_item_id"],
        "idea_id": request["idea_id"],
        "goal_id": request["goal_id"],
        "kind": "E2E_ACCEPTANCE_CANARY",
    }
    script = {
        "script_id": request["script_id"],
        "content_item_id": request["content_item_id"],
        "language": "pt-BR",
        "kind": "CANARY_PIPELINE_PROOF",
        "duration_seconds": duration,
    }
    controller = {
        "schema": "run001-e2e-canary-controller-evidence/v1",
        "status": "AUTHORIZED_FOR_RENDER_DISPATCH",
        "render_workflow": RENDER_WORKFLOW,
        "authorization_id": authorization.authorization_id,
        "harness_decision_id": authorization.harness_decision_id,
        "brain_decision_id": context["brain_decision_id"],
        "routing_id": routing.routing_id,
        "selected_capability_id": routing.selected_capability_id,
        "selected_executor_binding": routing.selected_executor_binding,
        "authorized_action": authorization.authorized_action,
        "execution_id": authorization.execution_id,
        "goal_id": request["goal_id"],
        "render_job_id": request["render_job_id"],
        "video_id": request["video_id"],
        "content_item_id": request["content_item_id"],
        "script_id": request["script_id"],
        "estimated_duration_seconds": duration,
        "review_only": True,
        "job18_unchanged": True,
        "job20_reused_as_final": False,
        "youtube_publication": False,
        "target_human_review_state": "READY_FOR_HUMAN_REVIEW",
    }
    return {
        "goal": goal,
        "video": video,
        "content-item": content_item,
        "script": script,
        "render-job": job,
        "controller-evidence": controller,
    }


def persist_bundle(bundle: dict[str, dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in bundle.items():
        (output_dir / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    bundle = build_canary_bundle(_load(args.request))
    persist_bundle(bundle, args.output_dir)
    evidence = bundle["controller-evidence"]
    print("E2E_CONTROLLER=PASS")
    print(f"RENDER_JOB_ID={evidence['render_job_id']}")
    print(f"VIDEO_ID={evidence['video_id']}")
    print(f"CONTENT_ITEM_ID={evidence['content_item_id']}")
    print(f"SCRIPT_ID={evidence['script_id']}")
    print(f"GOAL_ID={evidence['goal_id']}")
    print(f"EXECUTION_ID={evidence['execution_id']}")
    print(f"AUTHORIZATION_ID={evidence['authorization_id']}")
    print(f"RENDER_WORKFLOW={evidence['render_workflow']}")
    print("JOB18_UNCHANGED=YES")
    print("JOB20_REUSED_AS_FINAL=NO")
    print("NO_YOUTUBE_PUBLISH=YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
