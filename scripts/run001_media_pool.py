from __future__ import annotations

import argparse
import json
from typing import Any

from app.database.media_knowledge_repository import MediaKnowledgeRepository
from app.database.production_plan_repository import get_production_plan_by_content_item_id
from app.database.render_queue_repository import get_render_job
from app.main import initialize_application
from app.services.media_selection_service import MediaSelectionError
from app.services.media_worker_artifact_import_service import import_media_worker_artifact
from app.services.production_media_selection_service import build_media_pool_plan


FROZEN_JOB_ID = 18
FROZEN_EXECUTION_ID = "run-001-canary-render-18"
CANARY_JOB_ID = 19
TARGETS = {"A": 4, "B": 5}


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True), flush=True)


def _guard_checkpoints() -> dict[str, Any]:
    frozen = get_render_job(FROZEN_JOB_ID)
    if not frozen or frozen.get("status") != "running":
        raise RuntimeError("Job18 frozen checkpoint changed")
    if frozen.get("execution_id") != FROZEN_EXECUTION_ID:
        raise RuntimeError("Job18 execution_id changed")
    canary = get_render_job(CANARY_JOB_ID)
    if not canary or canary.get("status") != "completed":
        raise RuntimeError("Job19 canonical canary must be completed")
    return frozen


def _source_records(repository: MediaKnowledgeRepository) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in repository.list_records():
        metadata = (record.get("payload") or {}).get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("media_pool") is not None:
            continue
        records.append(record)
    return records


def _readiness(repository: MediaKnowledgeRepository) -> dict[str, Any]:
    sources = _source_records(repository)
    payloads = {int(record["id"]): record["payload"] for record in sources}
    videos: list[dict[str, Any]] = []
    all_ready = bool(payloads)
    for label, content_item_id in TARGETS.items():
        stored = get_production_plan_by_content_item_id(content_item_id)
        if stored is None or not isinstance(stored.get("production_plan"), dict):
            videos.append({"label": label, "content_item_id": content_item_id, "ready": False, "error": "ProductionPlan missing"})
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
            videos.append(
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
        videos.append(
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
    return {
        "ready": all_ready,
        "source_knowledge_ids": [int(record["id"]) for record in sources],
        "sources": [
            {
                "id": int(record["id"]),
                "source_path": record.get("source_path"),
                "analysis_version": record.get("analysis_version"),
            }
            for record in sources
        ],
        "videos": videos,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="RUN-001 JSON-only MediaKnowledge pool control")
    parser.add_argument("action", choices=("status", "ensure", "import"))
    parser.add_argument("--artifact-dir")
    args = parser.parse_args()

    initialize_application()
    frozen_before = _guard_checkpoints()
    repository = MediaKnowledgeRepository()

    imported = None
    if args.action == "import":
        if not args.artifact_dir:
            raise ValueError("--artifact-dir is required for import")
        imported = import_media_worker_artifact(args.artifact_dir)

    readiness = _readiness(repository)
    pool = None
    if args.action == "ensure":
        if not readiness["ready"]:
            raise RuntimeError("RUN-001 media pool is not ready; import additional MediaKnowledge first")
        pool = repository.ensure_pool(
            knowledge_ids=readiness["source_knowledge_ids"],
            pool_name="run001-ab",
        )

    if get_render_job(FROZEN_JOB_ID) != frozen_before:
        raise RuntimeError("JOB18_UNCHANGED assertion failed")

    _emit(
        {
            "RUN001_MEDIA_POOL": "PASS" if readiness["ready"] else "BLOCKED",
            "ACTION": args.action,
            "JOB18_UNCHANGED": "YES",
            "JOB19_STATUS": "completed",
            "MEDIA_POOL_READY": readiness["ready"],
            "SOURCE_KNOWLEDGE_IDS": readiness["source_knowledge_ids"],
            "SOURCES": readiness["sources"],
            "VIDEOS": readiness["videos"],
            "IMPORTED": imported,
            "POOL": pool,
        }
    )
    return 0 if readiness["ready"] or args.action == "import" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _emit({"RUN001_MEDIA_POOL": "BLOCKED", "ERROR": str(exc)})
        raise
