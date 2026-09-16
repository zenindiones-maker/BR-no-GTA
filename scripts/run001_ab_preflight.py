from __future__ import annotations

import json
from typing import Any

from app.database.connection import get_connection
from app.database.gta6_goal_repository import (
    get_gta6_goal,
    get_gta6_goal_artifacts_by_idea_id,
)
from app.database.media_knowledge_repository import MediaKnowledgeRepository
from app.database.production_plan_repository import get_production_plan_by_content_item_id
from app.database.queue_repository import list_active_queue_items
from app.database.render_queue_repository import get_render_job
from app.main import initialize_application
from app.services.media_selection_service import MediaSelectionError
from app.services.production_media_selection_service import build_media_pool_plan


FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_JOB_ID = 19
TARGETS = {"A": 4, "B": 5}


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


def _source_records() -> list[dict[str, Any]]:
    repository = MediaKnowledgeRepository()
    records: list[dict[str, Any]] = []
    for record in repository.list_records():
        metadata = (record.get("payload") or {}).get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("media_pool") is not None:
            continue
        records.append(record)
    return records


def _media_pool_readiness(records: list[dict[str, Any]]) -> tuple[bool, list[dict[str, Any]]]:
    payloads = {int(record["id"]): record["payload"] for record in records}
    outputs: list[dict[str, Any]] = []
    all_ready = bool(payloads)
    for label, content_item_id in TARGETS.items():
        stored = get_production_plan_by_content_item_id(content_item_id)
        if stored is None or not isinstance(stored.get("production_plan"), dict):
            outputs.append({"label": label, "content_item_id": content_item_id, "ready": False, "error": "ProductionPlan missing"})
            all_ready = False
            continue
        plan = stored["production_plan"]
        scenes = plan.get("scenes") or []
        durations = [float(scene.get("duration_seconds") or 0) for scene in scenes if isinstance(scene, dict)]
        try:
            allocation = build_media_pool_plan(
                knowledge_payloads=payloads,
                scene_durations=durations,
                allocation_seed=content_item_id,
            )
        except (MediaSelectionError, ValueError) as exc:
            outputs.append(
                {
                    "label": label,
                    "content_item_id": content_item_id,
                    "ready": False,
                    "required_seconds": sum(durations),
                    "error": str(exc),
                }
            )
            all_ready = False
            continue
        outputs.append(
            {
                "label": label,
                "content_item_id": content_item_id,
                "ready": True,
                "required_seconds": allocation["required_seconds"],
                "available_seconds": allocation["available_seconds"],
                "scene_count": allocation["scene_count"],
                "used_knowledge_ids": allocation["used_knowledge_ids"],
            }
        )
    return all_ready, outputs


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
    if canary is None or canary.get("status") != "completed":
        raise RuntimeError("Job19 canonical canary checkpoint is not completed")

    candidates = _candidate_rows()
    media_records = _source_records()
    pool_ready, video_readiness = _media_pool_readiness(media_records)
    status = "PASS" if pool_ready else "BLOCKED"

    print(
        json.dumps(
            {
                "RUN001_AB_PREFLIGHT": status,
                "JOB18_UNCHANGED": "YES",
                "JOB18_STATUS": frozen.get("status"),
                "JOB19_STATUS": canary.get("status"),
                "ELIGIBLE_QUEUED_GOALS": len(candidates),
                "CANDIDATES": candidates,
                "MEDIA_POOL_READY": pool_ready,
                "MEDIA_KNOWLEDGE": [
                    {
                        "id": int(record["id"]),
                        "source_path": record.get("source_path"),
                        "analysis_version": record.get("analysis_version"),
                    }
                    for record in media_records
                ],
                "VIDEO_MEDIA_READINESS": video_readiness,
                "NEXT_ACTION": (
                    "run scripts/run001_media_pool.py ensure and pass its pool id to run001_ab_control.py"
                    if pool_ready
                    else "import additional JSON-only media-worker artifacts; do not create A/B RenderJobs yet"
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if pool_ready else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {"RUN001_AB_PREFLIGHT": "BLOCKED", "ERROR": str(exc)},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        raise
