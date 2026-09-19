from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")
os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning")
os.environ.setdefault("BR_RENDER_EXECUTOR", "github_actions")

from app.database.connection import get_connection
from app.database.gta6_goal_repository import get_gta6_goal_artifacts
from app.database.render_queue_repository import get_render_job, update_render_job_payload
from app.database.video_repository import get_video
from app.main import initialize_application
from app.services.audiovisual_render_request_service import build_worker_safe_render_job
from app.services.current_audio_contract_service import current_audio_contract
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.render_job_handoff_service import build_artifact_descriptor
from app.workers.professional_audiovisual_worker import validate_product_job
from scripts.video_a_current_contract_recovery import (
    GOAL_ID, SUCCESSOR_RENDER_JOB_ID, VIDEO_ID,
    _print_audio_gate, _proven_v4_render_binding,
)

REQUEST_PATH = Path(".run/video-a-current-product-e2e.request.json")


def _request() -> dict[str, Any]:
    value = json.loads(REQUEST_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("VIDEO A E2E request must be an object")
    return value


def _previous_render_run_id() -> int:
    value = int(_request().get("previous_render_run_id") or 0)
    if value <= 0:
        raise RuntimeError("request previous_render_run_id is required for Job2 resume")
    return value


def _gh_json(command: list[str]) -> Any:
    return json.loads(run_github_actions_command(command))


def _prove_previous_failure() -> dict[str, Any]:
    previous_render_run_id = _previous_render_run_id()
    run = _gh_json([
        "gh", "run", "view", str(previous_render_run_id),
        "--repo", os.environ["GITHUB_ACTIONS_REPOSITORY"],
        "--json", "databaseId,status,conclusion,headSha,url",
    ])
    if run.get("status") != "completed" or run.get("conclusion") != "failure":
        raise RuntimeError("previous Job2 render is not the proven completed failure")
    artifacts = _gh_json([
        "gh", "api",
        f"repos/{os.environ['GITHUB_ACTIONS_REPOSITORY']}/actions/runs/{previous_render_run_id}/artifacts",
    ])
    if any(
        item.get("name") == "render-output" and item.get("expired") is not True
        for item in artifacts.get("artifacts") or []
    ):
        raise RuntimeError("failed Job2 run has render-output; reconcile instead of retry")
    return {
        "run_id": previous_render_run_id,
        "status": "PROVEN_FAILED_BEFORE_RENDER_OUTPUT",
        "head_sha": run.get("headSha"),
        "url": run.get("url"),
    }


def _replace_render(job_id: int, render: dict[str, Any]) -> dict[str, Any]:
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT id,status,payload,attempt FROM render_jobs WHERE id=? LIMIT 1",
            (job_id,),
        ).fetchone()
        if row is None or row["status"] != "running":
            raise RuntimeError("Job2 must remain in running state for metadata-only retry")
        payload = json.loads(row["payload"])
        payload["render"] = dict(render)
        cursor = connection.execute(
            "UPDATE render_jobs SET payload=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='running'",
            (json.dumps(payload, ensure_ascii=False), job_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Job2 changed concurrently")
        connection.commit()
        payload.update(id=row["id"], status=row["status"], attempt=row["attempt"])
        return payload
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def prepare_retry(out: Path) -> None:
    initialize_application()
    proof = _prove_previous_failure()
    previous_render_run_id = int(proof["run_id"])
    state_path = out / "state.json"
    job_path = out / "render-job-handoff" / "render-job.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    checkpoint_job = json.loads(job_path.read_text(encoding="utf-8"))
    persisted = get_render_job(SUCCESSOR_RENDER_JOB_ID)
    if not persisted or persisted.get("status") != "running":
        raise RuntimeError("canonical Job2 is not recoverable")
    if int(state.get("VIDEO_ID") or 0) != VIDEO_ID or int(state.get("RENDER_JOB_ID") or 0) != SUCCESSOR_RENDER_JOB_ID:
        raise RuntimeError("checkpoint identity mismatch")
    if int(state.get("RENDER_RUN_ID") or 0) != previous_render_run_id:
        raise RuntimeError("checkpoint render run mismatch")
    if int((persisted.get("github_execution") or {}).get("run_id") or 0) != previous_render_run_id:
        raise RuntimeError("Job2 persisted run mismatch")
    artifacts = get_gta6_goal_artifacts(GOAL_ID) or {}
    if artifacts.get("video_id") != VIDEO_ID or artifacts.get("render_job_id") != SUCCESSOR_RENDER_JOB_ID:
        raise RuntimeError("Goal no longer points to Video1/Job2")
    video = get_video(VIDEO_ID)
    if not video or video.get("status") != "draft":
        raise RuntimeError("Video1 must still be draft")

    audio = current_audio_contract()
    for candidate in (checkpoint_job, persisted):
        if candidate.get("current_audio_contract_fingerprint") != audio["CURRENT_AUDIO_CONTRACT_FINGERPRINT"]:
            raise RuntimeError("Job2 audio checkpoint is stale")
        if (candidate.get("narration") or {}).get("voice") != audio["VOICE_SHORT_NAME"]:
            raise RuntimeError("Job2 official voice changed")
        if (candidate.get("subtitles") or {}).get("enabled") is not False:
            raise RuntimeError("Job2 subtitle policy changed")

    lineage = dict(persisted.get("lineage") or {})
    render = dict(persisted.get("render") or {})
    render["learning_profile"] = _proven_v4_render_binding(
        routing_id=str(lineage["routing_id"]),
        authorization_id=str(persisted["authorization_id"]),
    )
    rebound = _replace_render(SUCCESSOR_RENDER_JOB_ID, render)
    canonical_handoff = dict(rebound)
    canonical_handoff.pop("github_execution", None)
    handoff = build_worker_safe_render_job(canonical_handoff)
    validate_product_job(handoff)
    _print_audio_gate(handoff)
    job_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")

    state.update({
        "status": "RETRY_HANDOFF_PREPARED",
        "CHECKPOINT_REUSE": "YES",
        "VIDEO_ID": VIDEO_ID,
        "RENDER_JOB_ID": SUCCESSOR_RENDER_JOB_ID,
        "PREVIOUS_RENDER_RUN_ID": previous_render_run_id,
        "RENDER_RUN_ID": None,
        "CURRENT_AUDIO_CONTRACT_FINGERPRINT": audio["CURRENT_AUDIO_CONTRACT_FINGERPRINT"],
        "previous_render_proof": proof,
    })
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print("RENDER_RETRY_MODE=REUSE_EXISTING_JOB2")
    print("CHECKPOINT_REUSE=YES")
    print("VIDEO_ID=1")
    print("RENDER_JOB_ID=2")


def dispatch_retry(
    out: Path,
    *,
    artifact_id: int,
    artifact_name: str,
    producer_run_id: int,
    source_sha: str,
) -> None:
    initialize_application()
    proof = _prove_previous_failure()
    previous_render_run_id = int(proof["run_id"])
    state_path = out / "state.json"
    job_path = out / "render-job-handoff" / "render-job.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    job = json.loads(job_path.read_text(encoding="utf-8"))
    persisted = get_render_job(SUCCESSOR_RENDER_JOB_ID)
    if not persisted or persisted.get("status") != "running":
        raise RuntimeError("Job2 is no longer running; reconcile before retry")
    if int((persisted.get("github_execution") or {}).get("run_id") or 0) != previous_render_run_id:
        raise RuntimeError("Job2 previous run changed")
    _print_audio_gate(job)

    descriptor = build_artifact_descriptor(
        render_job_path=job_path,
        job=job,
        artifact_id=artifact_id,
        artifact_name=artifact_name,
        producer_run_id=producer_run_id,
        producer_workflow="video-a-current-product-e2e.yml",
        source_sha=source_sha,
    )
    compact = json.dumps(descriptor, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    dispatched = GitHubActionsDispatcher(
        command_runner=run_github_actions_command
    ).dispatch(
        repository=os.environ["GITHUB_ACTIONS_REPOSITORY"],
        workflow="render-worker.yml",
        ref=os.environ["GITHUB_ACTIONS_RENDER_REF"],
        inputs={
            "render_job": "",
            "render_job_descriptor": compact,
            "brain_decision_id": str(job["brain_decision_id"]),
            "execution_id": str(job["execution_id"]),
            "authorized_action": str(job["authorized_action"]),
        },
    )
    github_execution = {
        "run_id": dispatched.run_id,
        "repository": dispatched.repository,
        "workflow": dispatched.workflow,
        "ref": dispatched.ref,
        "artifact_name": "render-output",
        "transport_mode": "artifact",
        "render_job_handoff_artifact_id": artifact_id,
        "render_job_handoff_artifact_name": artifact_name,
        "render_job_handoff_producer_run_id": producer_run_id,
        "render_job_handoff_source_sha": source_sha,
        "retry_of_run_id": previous_render_run_id,
        "same_render_job_id": SUCCESSOR_RENDER_JOB_ID,
    }
    update_render_job_payload(SUCCESSOR_RENDER_JOB_ID, github_execution=github_execution)
    state.update({
        "status": "RENDER_REDISPATCHED_SAME_JOB",
        "VIDEO_ID": VIDEO_ID,
        "RENDER_JOB_ID": SUCCESSOR_RENDER_JOB_ID,
        "PREVIOUS_RENDER_RUN_ID": previous_render_run_id,
        "RENDER_RUN_ID": dispatched.run_id,
        "github_execution": github_execution,
        "render_job_descriptor": descriptor,
    })
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "render-job-handoff-descriptor.json").write_text(
        json.dumps(descriptor, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("RENDER_RETRY_MODE=REUSE_EXISTING_JOB2")
    print(f"RENDER_RUN_ID={dispatched.run_id}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("prepare-retry", "dispatch-retry"))
    p.add_argument("--out", type=Path, default=Path("runtime/product-delivery"))
    p.add_argument("--artifact-id", type=int)
    p.add_argument("--artifact-name")
    p.add_argument("--producer-run-id", type=int)
    p.add_argument("--source-sha")
    a = p.parse_args()
    if a.action == "prepare-retry":
        prepare_retry(a.out)
    else:
        if not all((a.artifact_id, a.artifact_name, a.producer_run_id, a.source_sha)):
            raise SystemExit("artifact identity arguments are required")
        dispatch_retry(
            a.out,
            artifact_id=int(a.artifact_id),
            artifact_name=str(a.artifact_name),
            producer_run_id=int(a.producer_run_id),
            source_sha=str(a.source_sha),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
