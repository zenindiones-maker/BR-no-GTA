from __future__ import annotations

import json
import os
import sys
from typing import Any

# Canonical cloud executor configuration for RUN-001. These defaults only fill
# missing local configuration; explicit environment values still win.
os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")
os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_WORKFLOW", "render-worker.yml")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning")

from app.database.render_queue_repository import get_render_job
from app.services.audiovisual_executor_factory import create_audiovisual_executor
from app.services.gta6_goal_service import (
    get_artifacts,
    get_or_create_goal,
    update_artifacts,
)
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.production_execution_service import process_next_production_execution
from app.services.render_orchestration_service import execute_render_job


SOURCE_GOAL_ID = "d9767b1e-524c-4187-961d-ac8b32435506"
FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_TOPIC = "RUN-001 CANARY 2 — GTA6 Trailer 1 — isolated"
CANARY_DURATION_SECONDS = 45.0


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RuntimeError(f"{name} must be a positive integer")
    return value


def _route_execution(*, purpose: str):
    return route_harness_request(
        HarnessRoutingRequest(
            intent=purpose,
            authorized_action="EXECUTION",
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )


def _issue_goal_authorization(*, goal_id: str, purpose: str):
    routing = _route_execution(purpose=purpose)
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        lineage={
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": goal_id,
            "zero_cost_operation": True,
            "purpose": purpose,
        },
    )
    return routing, authorization


def _issue_render_authorization(*, goal_id: str, render_job_id: int, parent):
    routing = _route_execution(purpose="dispatch isolated RUN-001 canary render")
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id=parent.harness_decision_id,
        execution_id=parent.execution_id,
        lineage={
            "parent_authorization_id": parent.authorization_id,
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": goal_id,
            "render_job_id": render_job_id,
            "zero_cost_operation": True,
            "purpose": "run-001-canary-render",
        },
    )
    return routing, authorization


def _prepare_goal() -> tuple[dict[str, Any], dict[str, Any], Any]:
    source_artifacts = get_artifacts(goal_id=SOURCE_GOAL_ID)
    if source_artifacts.get("render_job_id") != FROZEN_JOB_ID:
        raise RuntimeError("Frozen source Goal no longer points to Job18; refusing to continue")

    source_ids = {
        key: _positive_int(source_artifacts.get(key), key)
        for key in ("idea_id", "script_id", "content_item_id")
    }

    canary = get_or_create_goal(
        goal_type="NEWS",
        topic=CANARY_TOPIC,
        priority="HIGH",
        opportunity_score=8.0,
        target_duration="45s",
    )
    if canary["goal_id"] == SOURCE_GOAL_ID:
        raise RuntimeError("Independent canary resolved to the frozen source Goal")

    artifacts = get_artifacts(goal_id=canary["goal_id"])
    existing_lineage = {
        key: artifacts.get(key)
        for key in ("idea_id", "script_id", "content_item_id")
        if artifacts.get(key) is not None
    }
    for key, value in existing_lineage.items():
        if value != source_ids[key]:
            raise RuntimeError(f"Existing canary {key} does not match the canonical source lineage")

    if artifacts.get("video_id") is not None and artifacts.get("render_job_id") is None:
        raise RuntimeError("Canary Goal is in partial Video state without RenderJob; refusing implicit recovery")

    if artifacts.get("render_job_id") is None:
        update_artifacts(goal_id=canary["goal_id"], **source_ids)
        _, authorization = _issue_goal_authorization(
            goal_id=canary["goal_id"],
            purpose="prepare isolated RUN-001 canary video and render job",
        )
        result = process_next_production_execution(
            authorization_to_context(authorization),
            goal_id=canary["goal_id"],
        )
        if not isinstance(result, dict) or result.get("stage") != "VIDEO":
            raise RuntimeError(f"Expected VIDEO preparation stage, got: {result!r}")
        artifacts = get_artifacts(goal_id=canary["goal_id"])
        return canary, artifacts, authorization

    render_job_id = _positive_int(artifacts.get("render_job_id"), "render_job_id")
    existing_job = get_render_job(render_job_id)
    if existing_job is None:
        raise RuntimeError("Canary Goal references a missing RenderJob")

    execution_id = existing_job.get("execution_id")
    decision_id = existing_job.get("brain_decision_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise RuntimeError("Existing canary RenderJob has no execution_id")
    if not isinstance(decision_id, str) or not decision_id:
        raise RuntimeError("Existing canary RenderJob has no brain_decision_id")

    # Create a fresh persisted authorization while preserving the canonical
    # execution/decision lineage already attached to this RenderJob.
    routing = _route_execution(purpose="resume isolated RUN-001 canary dispatch")
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id=decision_id,
        execution_id=execution_id,
        lineage={
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": canary["goal_id"],
            "render_job_id": render_job_id,
            "zero_cost_operation": True,
            "purpose": "run-001-canary-render-resume",
        },
    )
    return canary, artifacts, authorization


def main() -> int:
    frozen_before = get_render_job(FROZEN_JOB_ID)
    if frozen_before is None:
        raise RuntimeError("Frozen Job18 is missing")
    if frozen_before.get("status") != "running":
        raise RuntimeError(f"Frozen Job18 status changed: {frozen_before.get('status')!r}")
    if frozen_before.get("execution_id") != FROZEN_EXECUTION_ID:
        raise RuntimeError("Frozen Job18 execution_id changed")
    frozen_snapshot = _stable(frozen_before)

    canary, artifacts, preparation_authorization = _prepare_goal()
    render_job_id = _positive_int(artifacts.get("render_job_id"), "render_job_id")
    video_id = _positive_int(artifacts.get("video_id"), "video_id")
    if render_job_id == FROZEN_JOB_ID:
        raise RuntimeError("Independent canary unexpectedly resolved to Job18")

    job = get_render_job(render_job_id)
    if job is None:
        raise RuntimeError("Prepared canary RenderJob was not found")

    duration = float(job.get("estimated_duration_seconds"))
    if not 30.0 <= duration <= 60.0:
        raise RuntimeError(f"Canary duration outside 30–60 seconds: {duration}")
    if job.get("authorized_action") != "EXECUTION":
        raise RuntimeError("Canary RenderJob is not EXECUTION-authorized")
    if job.get("execution_id") == FROZEN_EXECUTION_ID:
        raise RuntimeError("Canary reused Job18 execution_id")

    status = job.get("status")
    github_execution = job.get("github_execution")

    if status == "queued":
        _, render_authorization = _issue_render_authorization(
            goal_id=canary["goal_id"],
            render_job_id=render_job_id,
            parent=preparation_authorization,
        )
        executor = create_audiovisual_executor()
        if executor is None:
            raise RuntimeError("GitHub Actions audiovisual executor is not configured")
        result = execute_render_job(
            render_job_id,
            executor=executor,
            execution_context=authorization_to_context(render_authorization),
        )
        if not result.pending or not result.github_execution:
            raise RuntimeError(f"Expected durable async GitHub dispatch, got: {result!r}")
        github_execution = result.github_execution
        job = get_render_job(render_job_id)
        status = job.get("status") if job else None
    elif status == "running" and github_execution:
        pass
    elif status == "completed" and github_execution:
        pass
    else:
        raise RuntimeError(
            f"Canary RenderJob is not safely dispatchable/resumable: status={status!r}, "
            f"github_execution={bool(github_execution)}"
        )

    frozen_after = get_render_job(FROZEN_JOB_ID)
    if _stable(frozen_after) != frozen_snapshot:
        raise RuntimeError("JOB18_UNCHANGED assertion failed")

    run_id = (github_execution or {}).get("run_id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise RuntimeError("GitHub Actions dispatch did not return a valid run_id")

    job = get_render_job(render_job_id) or job
    payload = {
        "RUN001_STATUS": "CANARY_DISPATCHED",
        "CANARY_GOAL_ID": canary["goal_id"],
        "CANARY_RENDER_JOB_ID": render_job_id,
        "CANARY_VIDEO_ID": video_id,
        "CANARY_EXECUTION_ID": job.get("execution_id"),
        "CANARY_DURATION": duration,
        "CANARY_WORKFLOW_RUN_ID": run_id,
        "CANARY_RENDER_STATUS": job.get("status"),
        "JOB18_UNCHANGED": "YES",
        "ZERO_COST": "PASS",
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"RUN001_STATUS": "BLOCKED", "ERROR": str(exc)}, ensure_ascii=False))
        raise
