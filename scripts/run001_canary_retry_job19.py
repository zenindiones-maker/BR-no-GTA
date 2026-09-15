from __future__ import annotations

import json
import os
from typing import Any

os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")

from app.database.render_queue_repository import (
    get_render_job,
    update_render_job_payload,
)
from app.services.audiovisual_render_request_service import (
    build_audiovisual_render_request,
)
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.github_actions_run_tracker import GitHubActionsRunTracker
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
    validate_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.workers.audiovisual_worker import validate_job


REPOSITORY = "zenindiones-maker/BR-no-GTA"
WORKFLOW = "render-worker.yml"
REF = "work/gate6f-analytics-learning"
FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_JOB_ID = 19
CANARY_GOAL_ID = "fa38f057-1b5b-4c95-bb44-764bb8f22d95"


def _stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def main() -> int:
    frozen_before = get_render_job(FROZEN_JOB_ID)
    if frozen_before is None:
        raise RuntimeError("Frozen Job18 is missing")
    if frozen_before.get("status") != "running":
        raise RuntimeError(f"Frozen Job18 status changed: {frozen_before.get('status')!r}")
    if frozen_before.get("execution_id") != FROZEN_EXECUTION_ID:
        raise RuntimeError("Frozen Job18 execution_id changed")
    frozen_snapshot = _stable(frozen_before)

    job = get_render_job(CANARY_JOB_ID)
    if job is None:
        raise RuntimeError("Canary Job19 is missing")
    if job.get("status") != "running":
        raise RuntimeError(f"Job19 must remain running for bounded retry; got {job.get('status')!r}")
    if job.get("render_job_id") not in (None, CANARY_JOB_ID) and job.get("id") != CANARY_JOB_ID:
        raise RuntimeError("Job19 identity mismatch")
    if job.get("execution_id") == FROZEN_EXECUTION_ID:
        raise RuntimeError("Job19 unexpectedly reused Job18 execution_id")
    if job.get("authorized_action") != "EXECUTION":
        raise RuntimeError("Job19 is not EXECUTION-authorized")
    duration = float(job.get("estimated_duration_seconds"))
    if not 30.0 <= duration <= 60.0:
        raise RuntimeError(f"Job19 duration outside canary bounds: {duration}")

    previous = job.get("github_execution")
    if not isinstance(previous, dict):
        raise RuntimeError("Job19 has no persisted GitHub execution to recover")
    previous_run_id = previous.get("run_id")
    if not isinstance(previous_run_id, int) or previous_run_id <= 0:
        raise RuntimeError("Job19 previous GitHub run_id is invalid")

    tracker = GitHubActionsRunTracker(command_runner=run_github_actions_command)
    previous_status = tracker.get_status(REPOSITORY, previous_run_id)
    if not previous_status.failed:
        raise RuntimeError(
            "Refusing retry because previous GitHub run is not a completed failure: "
            f"status={previous_status.status!r} conclusion={previous_status.conclusion!r}"
        )

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="retry RUN-001 Job19 after pre-render validation failure",
            authorized_action="EXECUTION",
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        harness_decision_id=job["brain_decision_id"],
        execution_id=job["execution_id"],
        lineage={
            "routing_id": routing.routing_id,
            "selected_capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": CANARY_GOAL_ID,
            "render_job_id": CANARY_JOB_ID,
            "previous_run_id": previous_run_id,
            "zero_cost_operation": True,
            "purpose": "run-001-canary-job19-validation-retry",
        },
    )
    validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject="action:EXECUTION",
        expected_execution_id=job["execution_id"],
    )

    request = build_audiovisual_render_request(job)
    worker_job = json.loads(request["render_job"])
    # Prove locally that the exact payload about to cross the cloud boundary
    # passes the same first gate that failed in the previous run.
    validate_job(worker_job, allow_runtime_plan=True)

    dispatcher = GitHubActionsDispatcher(command_runner=run_github_actions_command)
    dispatched = dispatcher.dispatch(
        repository=REPOSITORY,
        workflow=WORKFLOW,
        ref=REF,
        inputs=request,
    )
    github_execution = {
        "run_id": dispatched.run_id,
        "repository": REPOSITORY,
        "workflow": WORKFLOW,
        "ref": REF,
        "artifact_name": "render-output",
        "retry_of_run_id": previous_run_id,
    }
    update_render_job_payload(
        CANARY_JOB_ID,
        github_execution=github_execution,
    )
    consume_harness_authorization(authorization)

    frozen_after = get_render_job(FROZEN_JOB_ID)
    if _stable(frozen_after) != frozen_snapshot:
        raise RuntimeError("JOB18_UNCHANGED assertion failed")

    persisted = get_render_job(CANARY_JOB_ID)
    payload = {
        "RUN001_STATUS": "CANARY_JOB19_REDISPATCHED",
        "CANARY_RENDER_JOB_ID": CANARY_JOB_ID,
        "CANARY_EXECUTION_ID": persisted.get("execution_id") if persisted else job.get("execution_id"),
        "CANARY_DURATION": duration,
        "PREVIOUS_WORKFLOW_RUN_ID": previous_run_id,
        "CANARY_WORKFLOW_RUN_ID": dispatched.run_id,
        "CANARY_RENDER_STATUS": persisted.get("status") if persisted else None,
        "PRE_DISPATCH_WORKER_VALIDATION": "PASS",
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
