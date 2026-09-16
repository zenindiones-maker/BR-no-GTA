from __future__ import annotations

import argparse
import json
import os
from typing import Any

# The A15 remains control-plane only. Heavy media work is dispatched to Actions.
os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")
os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning")
os.environ.setdefault("BR_RENDER_EXECUTOR", "github_actions")

from app.database.gta6_goal_repository import get_gta6_goal, get_gta6_goal_artifacts
from app.database.production_plan_repository import get_production_plan_by_content_item_id
from app.database.render_queue_repository import get_render_job
from app.integrations.deepseek_harness.server import br_execution_process_next
from app.main import initialize_application


FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_JOB_ID = 19
GOALS = {
    "A": {
        "goal_id": "93f99ddc-09c7-474b-8849-6981aa78d60c",
        "script_id": 8,
        "content_item_id": 4,
        "production_plan_id": 3,
    },
    "B": {
        "goal_id": "10ea70fb-8255-4f89-a6ce-6d2ffced3982",
        "script_id": 9,
        "content_item_id": 5,
        "production_plan_id": 4,
    },
}


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _frozen_snapshot() -> dict[str, Any]:
    job = get_render_job(FROZEN_JOB_ID)
    if not job:
        raise RuntimeError("Job18 frozen checkpoint is missing")
    if job.get("status") != "running":
        raise RuntimeError(f"Job18 status changed: {job.get('status')!r}")
    if job.get("execution_id") != FROZEN_EXECUTION_ID:
        raise RuntimeError("Job18 execution_id changed")
    return job


def _verify_canary() -> None:
    job = get_render_job(CANARY_JOB_ID)
    if not job or job.get("status") != "completed":
        raise RuntimeError("Job19 canonical canary checkpoint is not completed")


def _verify_editorial(label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = GOALS[label]
    goal_id = expected["goal_id"]
    goal = get_gta6_goal(goal_id)
    if goal is None:
        raise RuntimeError(f"VIDEO {label} canonical Goal is missing: {goal_id}")
    artifacts = get_gta6_goal_artifacts(goal_id)
    if not artifacts:
        raise RuntimeError(f"VIDEO {label} Goal artifacts are missing")
    for field in ("script_id", "content_item_id"):
        if artifacts.get(field) != expected[field]:
            raise RuntimeError(
                f"VIDEO {label} canonical {field} mismatch: "
                f"expected={expected[field]!r} actual={artifacts.get(field)!r}"
            )
    stored = get_production_plan_by_content_item_id(expected["content_item_id"])
    if stored is None:
        raise RuntimeError(f"VIDEO {label} ProductionPlan is missing")
    if stored.get("id") != expected["production_plan_id"]:
        raise RuntimeError(
            f"VIDEO {label} ProductionPlan id mismatch: "
            f"expected={expected['production_plan_id']} actual={stored.get('id')}"
        )
    plan = stored.get("production_plan") or {}
    duration = float(plan.get("estimated_duration_seconds") or 0)
    if abs(duration - 1500.0) > 0.001:
        raise RuntimeError(f"VIDEO {label} duration contract mismatch: {duration}")
    return goal, artifacts


def _state(label: str) -> dict[str, Any]:
    goal, artifacts = _verify_editorial(label)
    render_job_id = artifacts.get("render_job_id")
    render_job = get_render_job(render_job_id) if _positive_int(render_job_id) else None
    github_execution = (
        render_job.get("github_execution")
        if isinstance(render_job, dict) and isinstance(render_job.get("github_execution"), dict)
        else None
    )
    locator = (
        github_execution.get("artifact_locator")
        if isinstance(github_execution, dict) and isinstance(github_execution.get("artifact_locator"), dict)
        else None
    )
    return {
        "label": label,
        "goal_id": GOALS[label]["goal_id"],
        "goal_status": goal.get("status"),
        "goal_stage": goal.get("current_stage"),
        "script_id": artifacts.get("script_id"),
        "content_item_id": artifacts.get("content_item_id"),
        "production_plan_id": GOALS[label]["production_plan_id"],
        "video_id": artifacts.get("video_id"),
        "render_job_id": render_job_id,
        "render_status": render_job.get("status") if render_job else None,
        "render_execution_id": render_job.get("execution_id") if render_job else None,
        "render_run_id": github_execution.get("run_id") if github_execution else None,
        "artifact_id": locator.get("artifact_id") if locator else None,
        "media_uri": locator.get("media_uri") if locator else None,
        "youtube_publication_id": artifacts.get("youtube_publication_id"),
    }


def _emit(payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RUN-001 A/B exact Goal control-plane driver; never renders media on the phone."
    )
    parser.add_argument("action", choices=("status", "advance"))
    parser.add_argument("--video", choices=("A", "B"))
    args = parser.parse_args()

    initialize_application()
    frozen_before = _frozen_snapshot()
    _verify_canary()

    if args.action == "status":
        _emit(
            {
                "RUN001_AB_CONTROL": "STATUS",
                "JOB18_UNCHANGED": "YES",
                "JOB19_STATUS": "completed",
                "VIDEOS": [_state("A"), _state("B")],
            }
        )
        return 0

    if args.video is None:
        raise ValueError("--video A or --video B is required for advance")

    label = args.video
    before = _state(label)
    envelope = json.loads(br_execution_process_next(goal_id=GOALS[label]["goal_id"]))
    result = envelope.get("result")
    after = _state(label)

    if get_render_job(FROZEN_JOB_ID) != frozen_before:
        raise RuntimeError("JOB18_UNCHANGED assertion failed")

    _emit(
        {
            "RUN001_AB_CONTROL": "ADVANCE_PASS",
            "VIDEO": label,
            "GOAL_ID": GOALS[label]["goal_id"],
            "JOB18_UNCHANGED": "YES",
            "JOB19_STATUS": "completed",
            "BEFORE": before,
            "HARNESS_RESULT": result,
            "AFTER": after,
            "NOTE": (
                "One exact Harness-authorized step executed. If render_status is running, "
                "rerun this same exact-video command later to metadata-reconcile the cloud run; "
                "no MP4 is downloaded to the A15."
            ),
        }
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _emit({"RUN001_AB_CONTROL": "BLOCKED", "ERROR": str(exc)})
        raise
