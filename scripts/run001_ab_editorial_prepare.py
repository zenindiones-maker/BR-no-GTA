from __future__ import annotations

import json
import os

# RUN-001 A/B keeps the A15 as control-plane only. Editorial AI is executed by
# the bounded zero-cost OmniRoute GitHub Actions transport selected by Harness.
os.environ.setdefault("ZERO_COST_OPERATION", "TRUE")
os.environ.setdefault("GITHUB_ACTIONS_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("BR_OMNIROUTE_REPOSITORY", "zenindiones-maker/BR-no-GTA")
os.environ.setdefault("BR_OMNIROUTE_REF", "work/gate6f-analytics-learning")
os.environ.setdefault("GITHUB_ACTIONS_RENDER_REF", "work/gate6f-analytics-learning")

from app.database.gta6_goal_repository import get_gta6_goal_artifacts
from app.database.queue_repository import (
    get_active_queue_item_by_idea,
    requeue_processing_queue_item_by_id,
)
from app.database.render_queue_repository import get_render_job
from app.integrations.deepseek_harness.server import br_editorial_process_next
from app.main import initialize_application

FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_JOB_ID = 19
TARGET_DURATION_SECONDS = 1500.0
GOALS = (
    ("A", "93f99ddc-09c7-474b-8849-6981aa78d60c"),
    ("B", "10ea70fb-8255-4f89-a6ce-6d2ffced3982"),
)


def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _recover_interrupted_targeted_claim(*, label: str, goal_id: str) -> None:
    """Recover only an A/B claim left processing before canonical lineage advanced."""
    artifacts = get_gta6_goal_artifacts(goal_id)
    if not artifacts:
        raise RuntimeError(f"VIDEO {label} Goal artifacts are missing")

    idea_id = artifacts.get("idea_id")
    if not _positive_int(idea_id):
        raise RuntimeError(f"VIDEO {label} Goal has invalid idea_id")

    queue_item = get_active_queue_item_by_idea(idea_id)
    if queue_item is None or queue_item.get("status") != "processing":
        return

    # If durable downstream lineage already exists, never rewind the queue.
    if any(
        _positive_int(artifacts.get(field))
        for field in ("script_id", "content_item_id", "render_job_id")
    ):
        raise RuntimeError(
            f"VIDEO {label} has processing editorial claim with durable lineage; "
            "refusing automatic rewind"
        )

    queue_id = queue_item.get("id")
    if not _positive_int(queue_id):
        raise RuntimeError(f"VIDEO {label} processing queue item has invalid id")

    if not requeue_processing_queue_item_by_id(
        queue_id,
        expected_idea_id=idea_id,
    ):
        raise RuntimeError(
            f"VIDEO {label} interrupted editorial claim could not be safely requeued"
        )

    print(
        json.dumps(
            {
                "RUN001_AB_EDITORIAL": "RECOVERED_INTERRUPTED_CLAIM",
                "VIDEO": label,
                "GOAL_ID": goal_id,
                "QUEUE_ID": queue_id,
                "JOB18_UNCHANGED": "YES",
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        flush=True,
    )


def main() -> int:
    initialize_application()
    frozen = get_render_job(FROZEN_JOB_ID)
    if not frozen or frozen.get("status") != "running":
        raise RuntimeError("Job18 frozen checkpoint changed")
    if frozen.get("execution_id") != FROZEN_EXECUTION_ID:
        raise RuntimeError("Job18 execution_id changed")
    canary = get_render_job(CANARY_JOB_ID)
    if not canary or canary.get("status") != "completed":
        raise RuntimeError("Job19 must be completed before A/B editorial preparation")

    outputs = []
    for label, goal_id in GOALS:
        _recover_interrupted_targeted_claim(label=label, goal_id=goal_id)
        print(
            json.dumps(
                {
                    "RUN001_AB_EDITORIAL": "IN_PROGRESS",
                    "VIDEO": label,
                    "STAGE": "HARNESS_EDITORIAL_AI",
                    "GOAL_ID": goal_id,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            flush=True,
        )

        envelope = json.loads(
            br_editorial_process_next(
                goal_id=goal_id,
                target_duration_seconds=TARGET_DURATION_SECONDS,
            )
        )
        result = envelope.get("result") or {}
        plan = result.get("production_plan") or {}
        duration = float(plan.get("estimated_duration_seconds") or 0)
        if abs(duration - TARGET_DURATION_SECONDS) > 0.001:
            raise RuntimeError(f"VIDEO {label} duration contract mismatch: {duration}")
        scenes = plan.get("scenes") or []
        if not scenes:
            raise RuntimeError(f"VIDEO {label} has no production scenes")
        maximum = max(float(scene.get("duration_seconds") or 0) for scene in scenes)
        if maximum > 30.001:
            raise RuntimeError(f"VIDEO {label} scene duration boundary failed: {maximum}")
        outputs.append({
            "label": label,
            "goal_id": goal_id,
            "script_id": (result.get("script") or {}).get("id"),
            "content_item_id": (result.get("content_item") or {}).get("id"),
            "production_plan_id": result.get("production_plan_id"),
            "duration_seconds": duration,
            "scene_count": len(scenes),
            "max_scene_seconds": maximum,
            "status": result.get("status"),
        })
        print(
            json.dumps(
                {
                    "RUN001_AB_EDITORIAL": "VIDEO_EDITORIAL_PASS",
                    "VIDEO": label,
                    "GOAL_ID": goal_id,
                    "DURATION_SECONDS": duration,
                    "SCENE_COUNT": len(scenes),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            flush=True,
        )

    if get_render_job(FROZEN_JOB_ID) != frozen:
        raise RuntimeError("JOB18_UNCHANGED assertion failed")

    print(json.dumps({
        "RUN001_AB_EDITORIAL": "PASS",
        "JOB18_UNCHANGED": "YES",
        "JOB19_STATUS": "completed",
        "VIDEOS": outputs,
    }, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"RUN001_AB_EDITORIAL": "BLOCKED", "ERROR": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        raise
