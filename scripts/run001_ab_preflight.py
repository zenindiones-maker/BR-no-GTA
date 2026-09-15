from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection
from app.database.gta6_goal_repository import (
    get_gta6_goal,
    get_gta6_goal_artifacts_by_idea_id,
)
from app.database.queue_repository import list_active_queue_items
from app.database.render_queue_repository import get_render_job
from app.main import initialize_application


FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_JOB_ID = 19


def _media_knowledge_inventory(limit: int = 8) -> list[dict[str, Any]]:
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT id, source_path, analysis_version
            FROM media_knowledge
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def _candidate_rows(limit: int = 8) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_goals: set[str] = set()

    for queue_item in list_active_queue_items():
        if queue_item.get("status") != "queued":
            continue
        idea_id = queue_item.get("idea_id")
        if not isinstance(idea_id, int) or isinstance(idea_id, bool) or idea_id <= 0:
            continue
        artifacts = get_gta6_goal_artifacts_by_idea_id(idea_id)
        if not artifacts:
            continue
        goal_id = artifacts.get("goal_id")
        if not isinstance(goal_id, str) or not goal_id or goal_id in seen_goals:
            continue
        seen_goals.add(goal_id)

        render_job_id = artifacts.get("render_job_id")
        if render_job_id in {FROZEN_JOB_ID, CANARY_JOB_ID}:
            continue
        goal = get_gta6_goal(goal_id)
        if goal is None:
            continue

        rows.append(
            {
                "goal_id": goal_id,
                "goal_status": goal.get("status"),
                "target_duration": goal.get("target_duration"),
                "idea_id": idea_id,
                "queue_id": queue_item.get("id"),
                "queue_priority_score": queue_item.get("priority_score"),
                "script_id": artifacts.get("script_id"),
                "content_item_id": artifacts.get("content_item_id"),
                "video_id": artifacts.get("video_id"),
                "render_job_id": render_job_id,
            }
        )
        if len(rows) >= limit:
            break

    return rows


def main() -> int:
    initialize_application()

    frozen = get_render_job(FROZEN_JOB_ID)
    if frozen is None:
        raise RuntimeError("Job18 is missing")
    if frozen.get("status") != "running":
        raise RuntimeError(f"Job18 status changed: {frozen.get('status')!r}")
    if frozen.get("execution_id") != FROZEN_EXECUTION_ID:
        raise RuntimeError("Job18 execution_id changed")

    canary = get_render_job(CANARY_JOB_ID)
    if canary is None:
        raise RuntimeError("Job19 checkpoint is missing")

    candidates = _candidate_rows()
    inventory = _media_knowledge_inventory()

    print(
        json.dumps(
            {
                "RUN001_AB_PREFLIGHT": "PASS",
                "JOB18_UNCHANGED": "YES",
                "JOB18_STATUS": frozen.get("status"),
                "JOB19_STATUS": canary.get("status"),
                "ELIGIBLE_QUEUED_GOALS": len(candidates),
                "CANDIDATES": candidates,
                "MEDIA_KNOWLEDGE": inventory,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "RUN001_AB_PREFLIGHT": "BLOCKED",
                    "ERROR": str(exc),
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        raise
