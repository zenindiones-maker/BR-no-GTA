from __future__ import annotations

import json

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
