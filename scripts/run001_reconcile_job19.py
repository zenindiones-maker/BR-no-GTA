from __future__ import annotations

import json
import os
from typing import Any

# Reconcile the already-completed cloud run against the canonical A15 runtime DB.
# This script MUST NOT dispatch another workflow run.
os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")
os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_WORKFLOW", "render-worker.yml")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning")
os.environ.setdefault("GITHUB_ACTIONS_ARTIFACT_NAME", "render-output")

from app.database.render_queue_repository import get_render_job
from app.database.video_repository import get_video
from app.services.audiovisual_executor_factory import create_audiovisual_executor
from app.services.gta6_goal_service import get_artifacts, get_goal, resolve_and_sync_goal
from app.services.harness_execution_result import canonical_execution_result
from app.services.render_orchestration_service import resume_cloud_render_job


FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_JOB_ID = 19
CANARY_VIDEO_ID = 4
CANARY_GOAL_ID = "fa38f057-1b5b-4c95-bb44-764bb8f22d95"
CANARY_EXECUTION_ID = "7307774b-b6c4-48e7-8b43-b13dce9ec50f"
CANARY_RUN_ID = 34984341615
CANARY_ARTIFACT = "render-output"


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _assert_frozen_job18(job: dict[str, Any] | None) -> None:
    if job is None:
        raise RuntimeError("Frozen Job18 is missing")
    if job.get("status") != "running":
        raise RuntimeError(f"Frozen Job18 status changed: {job.get('status')!r}")
    if job.get("execution_id") != FROZEN_EXECUTION_ID:
        raise RuntimeError("Frozen Job18 execution_id changed")


def _validate_job19_before(job: dict[str, Any] | None) -> dict[str, Any]:
    if job is None:
        raise RuntimeError("Job19 is missing from the canonical runtime DB")
    if job.get("status") == "completed":
        # Idempotent read-only path for an already-reconciled runtime.
        return job
    if job.get("status") != "running":
        raise RuntimeError(f"Job19 is not recoverable: status={job.get('status')!r}")
    if job.get("video_id") != CANARY_VIDEO_ID:
        raise RuntimeError("Job19 video_id mismatch")
    if job.get("execution_id") != CANARY_EXECUTION_ID:
        raise RuntimeError("Job19 execution_id mismatch")
    github_execution = job.get("github_execution")
    if not isinstance(github_execution, dict):
        raise RuntimeError("Job19 has no persisted github_execution")
    if github_execution.get("run_id") != CANARY_RUN_ID:
        raise RuntimeError(
            f"Job19 run_id mismatch: {github_execution.get('run_id')!r} != {CANARY_RUN_ID}"
        )
    if github_execution.get("artifact_name") not in (None, CANARY_ARTIFACT):
        raise RuntimeError("Job19 artifact_name mismatch")
    return job


def main() -> int:
    if os.environ.get("ZERO_COST_OPERATION", "").upper() != "TRUE":
        raise RuntimeError("ZERO_COST_OPERATION must remain TRUE")

    frozen_before = get_render_job(FROZEN_JOB_ID)
    _assert_frozen_job18(frozen_before)
    frozen_snapshot = _stable(frozen_before)

    before = _validate_job19_before(get_render_job(CANARY_JOB_ID))

    artifacts = get_artifacts(goal_id=CANARY_GOAL_ID)
    if artifacts.get("render_job_id") != CANARY_JOB_ID:
        raise RuntimeError("Canary Goal does not point to Job19")
    if artifacts.get("video_id") != CANARY_VIDEO_ID:
        raise RuntimeError("Canary Goal does not point to Video4")

    if before.get("status") != "completed":
        executor = create_audiovisual_executor()
        if executor is None:
            raise RuntimeError("GitHub Actions audiovisual executor is not configured")

        result = resume_cloud_render_job(CANARY_JOB_ID, executor)
        if not result.success or result.pending or result.error:
            raise RuntimeError(f"Job19 cloud reconciliation failed: {result!r}")
        if not result.output_path:
            raise RuntimeError("Job19 reconciliation returned no output_path")

    after = get_render_job(CANARY_JOB_ID)
    if after is None or after.get("status") != "completed":
        raise RuntimeError("Job19 was not persisted as completed")
    if not after.get("output_path"):
        raise RuntimeError("Job19 completed without persisted output_path")

    video = get_video(CANARY_VIDEO_ID)
    if video is None or video.get("status") != "ready":
        raise RuntimeError(f"Video4 was not persisted as ready: {video!r}")
    if video.get("file_path") != after.get("output_path"):
        raise RuntimeError("Video4 file_path does not match Job19 output_path")

    synced_goal = resolve_and_sync_goal(goal_id=CANARY_GOAL_ID)
    if synced_goal is None:
        raise RuntimeError("Canary Goal could not be synchronized")
    goal = get_goal(goal_id=CANARY_GOAL_ID)
    if goal is None:
        raise RuntimeError("Canary Goal disappeared after synchronization")

    frozen_after = get_render_job(FROZEN_JOB_ID)
    _assert_frozen_job18(frozen_after)
    if _stable(frozen_after) != frozen_snapshot:
        raise RuntimeError("JOB18_UNCHANGED assertion failed")

    github_execution = after.get("github_execution") or {}
    evidence = {
        "goal_id": CANARY_GOAL_ID,
        "render_job_id": CANARY_JOB_ID,
        "render_job_status": after.get("status"),
        "video_id": CANARY_VIDEO_ID,
        "video_status": video.get("status"),
        "goal_status": goal.get("status"),
        "goal_current_stage": goal.get("current_stage"),
        "github_run_id": github_execution.get("run_id"),
        "github_workflow": github_execution.get("workflow"),
        "artifact_name": github_execution.get("artifact_name", CANARY_ARTIFACT),
        "output_path": after.get("output_path"),
        "zero_cost_operation": True,
        "job18_unchanged": True,
    }
    canonical = canonical_execution_result(
        authority="DeepSeek Harness",
        authorized_action="EXECUTION",
        execution_id=after.get("execution_id"),
        harness_decision_id=after.get("brain_decision_id"),
        capability_id="production.render",
        operation="reconcile_cloud_render",
        executor="github_actions",
        status="completed",
        success=True,
        result={
            "goal_id": CANARY_GOAL_ID,
            "render_job_id": CANARY_JOB_ID,
            "video_id": CANARY_VIDEO_ID,
        },
        evidence=evidence,
        artifacts=(
            {
                "type": "github_actions_artifact",
                "run_id": CANARY_RUN_ID,
                "name": CANARY_ARTIFACT,
            },
            {"type": "mp4", "path": after.get("output_path")},
        ),
    ).to_dict()

    payload = {
        "RUN001_STATUS": "CANARY_RECONCILED",
        "JOB19_RECONCILIATION": "GREEN",
        "RENDER_JOB_19": after.get("status"),
        "VIDEO_4": video.get("status"),
        "CANARY_GOAL_ID": CANARY_GOAL_ID,
        "CANARY_GOAL_STAGE": goal.get("current_stage"),
        "CANARY_GOAL_STATUS": goal.get("status"),
        "CANARY_WORKFLOW_RUN_ID": CANARY_RUN_ID,
        "CANONICAL_EVIDENCE": "PASS",
        "HARNESS_RETURN": "PASS",
        "JOB18_UNCHANGED": "YES",
        "ZERO_COST": "PASS",
        "CANONICAL_RESULT": canonical,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"JOB19_RECONCILIATION": "BLOCKED", "ERROR": str(exc)},
                ensure_ascii=False,
            )
        )
        raise
