from __future__ import annotations

import argparse
import copy
import json
import os
from typing import Any

# Control-plane only. The A15 must never download the rendered media artifact.
os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")
os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning")
os.environ.setdefault("BR_RENDER_EXECUTOR", "github_actions")

from app.database.gta6_goal_repository import get_gta6_goal_artifacts
from app.database.render_queue_repository import get_render_job
from app.database.video_repository import get_video
from app.main import initialize_application
from app.services.audiovisual_executor_factory import create_audiovisual_executor
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.render_orchestration_service import (
    rebind_running_cloud_render_job_metadata,
)


REPOSITORY = "zenindiones-maker/BR-no-GTA"
WORKFLOW_FILE = "render-worker.yml"
WORKFLOW_NAME = "Render Worker"
REF = "work/gate6f-analytics-learning"
ARTIFACT_NAME = "render-output"
FIX_COMMIT = "ad30c2cfecebf04e2c8f23027ad31735b3297cba"

FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_JOB_ID = 19
JOB_ID = 20
VIDEO_ID = 5
PREVIOUS_RUN_ID = 35125183151
EXECUTION_ID = "acc83783-a9d2-4d38-8e17-b081c2a3eb97"
BRAIN_DECISION_ID = "827f0c32-0945-49ce-a38f-a0fe21e31910"
GOAL_ID = "93f99ddc-09c7-474b-8849-6981aa78d60c"
B_GOAL_ID = "10ea70fb-8255-4f89-a6ce-6d2ffced3982"


def _emit(payload: dict[str, Any]) -> None:
    print(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        flush=True,
    )


def _gh_json(command: list[str]) -> Any:
    output = run_github_actions_command(command)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub CLI returned invalid JSON") from exc


def _assert_frozen_job18() -> dict[str, Any]:
    job = get_render_job(FROZEN_JOB_ID)
    if not job:
        raise RuntimeError("Job18 frozen checkpoint is missing")
    if job.get("status") != "running":
        raise RuntimeError(f"Job18 status changed: {job.get('status')!r}")
    if job.get("execution_id") != FROZEN_EXECUTION_ID:
        raise RuntimeError("Job18 execution_id changed")
    return copy.deepcopy(job)


def _assert_local_checkpoint() -> dict[str, Any]:
    canary = get_render_job(CANARY_JOB_ID)
    if not canary or canary.get("status") != "completed":
        raise RuntimeError("Job19 canonical canary checkpoint is not completed")

    a_artifacts = get_gta6_goal_artifacts(GOAL_ID)
    if not a_artifacts:
        raise RuntimeError("VIDEO A canonical Goal artifacts are missing")
    if a_artifacts.get("video_id") != VIDEO_ID or a_artifacts.get("render_job_id") != JOB_ID:
        raise RuntimeError("VIDEO A canonical Video/RenderJob identity changed")

    b_artifacts = get_gta6_goal_artifacts(B_GOAL_ID) or {}
    if b_artifacts.get("render_job_id") is not None:
        raise RuntimeError("VIDEO B must remain unstarted while Job20 is recovered")

    job = get_render_job(JOB_ID)
    if not job or job.get("status") != "running":
        raise RuntimeError("Job20 is not in recoverable running state")
    if job.get("video_id") != VIDEO_ID:
        raise RuntimeError("Job20 video_id changed")
    if job.get("execution_id") != EXECUTION_ID:
        raise RuntimeError("Job20 execution_id changed")
    if job.get("brain_decision_id") != BRAIN_DECISION_ID:
        raise RuntimeError("Job20 brain_decision_id changed")
    if job.get("authorized_action") != "EXECUTION":
        raise RuntimeError("Job20 authorized_action changed")
    previous = job.get("github_execution") or {}
    if previous.get("run_id") != PREVIOUS_RUN_ID:
        raise RuntimeError("Job20 persisted cloud run changed before retry rebind")
    if previous.get("repository") != REPOSITORY or previous.get("workflow") != WORKFLOW_FILE:
        raise RuntimeError("Job20 persisted GitHub execution identity changed")
    if previous.get("ref") != REF:
        raise RuntimeError("Job20 persisted GitHub ref changed")
    return job


def _prove_retry_run(run_id: int) -> dict[str, Any]:
    run = _gh_json(
        [
            "gh",
            "run",
            "view",
            str(run_id),
            "--repo",
            REPOSITORY,
            "--json",
            "databaseId,event,headBranch,headSha,name,status,conclusion,url",
        ]
    )
    expected = {
        "databaseId": run_id,
        "event": "workflow_dispatch",
        "headBranch": REF,
        "name": WORKFLOW_NAME,
        "status": "completed",
        "conclusion": "success",
    }
    for key, value in expected.items():
        if run.get(key) != value:
            raise RuntimeError(
                f"Retry run proof mismatch for {key}: expected={value!r} actual={run.get(key)!r}"
            )

    head_sha = run.get("headSha")
    if not isinstance(head_sha, str) or len(head_sha) != 40:
        raise RuntimeError("Retry run does not expose a valid head SHA")
    compare = _gh_json(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/compare/{FIX_COMMIT}...{head_sha}",
        ]
    )
    if compare.get("status") not in {"ahead", "identical"}:
        raise RuntimeError("Retry run does not descend from the audio-requirements fix")

    artifacts = _gh_json(
        [
            "gh",
            "api",
            f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts",
        ]
    )
    matches = [
        item
        for item in artifacts.get("artifacts", [])
        if item.get("name") == ARTIFACT_NAME
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one {ARTIFACT_NAME!r} artifact; got {len(matches)}"
        )
    artifact = matches[0]
    if artifact.get("expired") is not False:
        raise RuntimeError("Retry render artifact is expired")
    size = artifact.get("size_in_bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise RuntimeError("Retry render artifact is empty")

    return {
        "run_id": run_id,
        "head_sha": head_sha,
        "run_url": run.get("url"),
        "artifact_id": artifact.get("id"),
        "artifact_size_in_bytes": size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebind RUN-001 Job20 to one proven successful retry without downloading MP4."
    )
    parser.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    if args.run_id <= 0 or args.run_id == PREVIOUS_RUN_ID:
        raise ValueError("--run-id must identify a distinct positive retry run")

    initialize_application()
    frozen_before = _assert_frozen_job18()
    _assert_local_checkpoint()
    proof = _prove_retry_run(args.run_id)

    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id=BRAIN_DECISION_ID,
        execution_id=EXECUTION_ID,
        lineage={
            "goal_id": GOAL_ID,
            "render_job_id": JOB_ID,
            "video_id": VIDEO_ID,
            "retry_of_run_id": PREVIOUS_RUN_ID,
            "proven_retry_run_id": args.run_id,
            "retry_head_sha": proof["head_sha"],
            "operation": "RUN001_JOB20_METADATA_REBIND",
        },
    )
    execution_context = authorization_to_context(authorization)
    executor = create_audiovisual_executor()
    if executor is None:
        raise RuntimeError("GitHub Actions audiovisual executor is unavailable")

    result = rebind_running_cloud_render_job_metadata(
        JOB_ID,
        executor,
        expected_previous_run_id=PREVIOUS_RUN_ID,
        proven_github_execution={
            "run_id": args.run_id,
            "repository": REPOSITORY,
            "workflow": WORKFLOW_FILE,
            "ref": REF,
            "artifact_name": ARTIFACT_NAME,
        },
        expected_video_id=VIDEO_ID,
        expected_execution_id=EXECUTION_ID,
        execution_context=execution_context,
    )

    if get_render_job(FROZEN_JOB_ID) != frozen_before:
        raise RuntimeError("JOB18_UNCHANGED assertion failed")
    if result.pending:
        raise RuntimeError("Retry run was proven completed but metadata reconciliation returned pending")
    if not result.success:
        raise RuntimeError(f"Retry metadata reconciliation failed: {result.error}")

    job = get_render_job(JOB_ID)
    video = get_video(VIDEO_ID)
    if not job or job.get("status") != "completed":
        raise RuntimeError("Job20 did not transition to completed")
    if not video or video.get("status") != "ready":
        raise RuntimeError("Video5 did not transition to ready")
    rebound = job.get("github_execution") or {}
    if rebound.get("run_id") != args.run_id:
        raise RuntimeError("Job20 did not retain the proven retry run")

    _emit(
        {
            "RUN001_JOB20_METADATA_REBIND": "PASS",
            "JOB18_UNCHANGED": "YES",
            "JOB19_STATUS": "completed",
            "VIDEO_B_UNCHANGED": "YES",
            "JOB20_ID": JOB_ID,
            "JOB20_STATUS": job.get("status"),
            "VIDEO_ID": VIDEO_ID,
            "VIDEO_STATUS": video.get("status"),
            "PREVIOUS_RUN_ID": PREVIOUS_RUN_ID,
            "RETRY_RUN_ID": args.run_id,
            "RETRY_HEAD_SHA": proof["head_sha"],
            "ARTIFACT_ID": proof["artifact_id"],
            "ARTIFACT_SIZE_IN_BYTES": proof["artifact_size_in_bytes"],
            "MEDIA_URI": result.output_path,
            "MP4_DOWNLOADED_TO_A15": "NO",
        }
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _emit({"RUN001_JOB20_METADATA_REBIND": "BLOCKED", "ERROR": str(exc)})
        raise
