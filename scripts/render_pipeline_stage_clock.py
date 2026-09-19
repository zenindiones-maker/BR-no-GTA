from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import time
from pathlib import Path

from app.services.performance_telemetry_service import emit_performance_event


_CATEGORY = {
    "preparation_wall": "MEDIA_PROCESSING_TIME",
    "editplan_vedit_ffmpeg": "RENDER_TIME",
    "visual_branding": "RENDER_TIME",
    "final_qa": "RENDER_TIME",
    "artifact_upload": "GITHUB_SETUP_TIME",
    "telegram_delivery": "TELEGRAM_TIME",
}


def _load(path: Path) -> dict:
    if not path.is_file():
        return {"version": "render-pipeline-stage-clock/v2", "stages": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("stage clock must be an object")
    value.setdefault("stages", {})
    value["version"] = "render-pipeline-stage-clock/v2"
    return value


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("start", "end"))
    p.add_argument("stage")
    p.add_argument("--path", type=Path, default=Path("runtime/render/pipeline-stage-clock.json"))
    p.add_argument("--category", default=None)
    args = p.parse_args()
    args.path.parent.mkdir(parents=True, exist_ok=True)
    data = _load(args.path)
    stage = data["stages"].setdefault(args.stage, {})
    if args.action == "start":
        stage["started_at"] = _utcnow()
        stage["started_monotonic_ns"] = time.monotonic_ns()
        stage["status"] = "RUNNING"
    else:
        started = int(stage.get("started_monotonic_ns") or 0)
        if started <= 0:
            raise SystemExit(f"stage {args.stage} was not started")
        finished_ns = time.monotonic_ns()
        elapsed_ms = max(0.0, (finished_ns - started) / 1_000_000.0)
        stage["finished_at"] = _utcnow()
        stage["finished_monotonic_ns"] = finished_ns
        stage["duration_ms"] = elapsed_ms
        stage["elapsed_seconds"] = elapsed_ms / 1000.0
        stage["category"] = args.category or _CATEGORY.get(args.stage, "IDLE/UNKNOWN_TIME")
        stage["status"] = "PASS"
        emit_performance_event(
            stage=f"render.{args.stage}",
            category=stage["category"],
            started_at=stage["started_at"],
            finished_at=stage["finished_at"],
            duration_ms=elapsed_ms,
            success=True,
            metadata={"source": "render_pipeline_stage_clock"},
        )
    args.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.action == "end":
        print(f"STAGE_{args.stage.upper()}_SECONDS={stage['elapsed_seconds']:.6f}")
        print(f"STAGE_{args.stage.upper()}_MS={stage['duration_ms']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
