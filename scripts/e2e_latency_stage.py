from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from app.services.performance_telemetry_service import emit_performance_event

WORK_CLASSES = {"NECESSARY", "REDUNDANT", "REPEATED", "WAITING", "BLOCKED", "INVALIDATED"}

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

def load(path: Path) -> dict:
    if not path.is_file():
        return {"version": "e2e-latency-stage/v1", "stages": {}}
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("latency stage state must be an object")
    value.setdefault("stages", {})
    return value

def fingerprint(path: str | None) -> str | None:
    if not path:
        return None
    p=Path(path)
    if not p.is_file():
        return None
    h=hashlib.sha256()
    with p.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("action", choices=("start","end"))
    p.add_argument("stage")
    p.add_argument("--state", type=Path, default=Path("runtime/product-delivery/latency-stages.json"))
    p.add_argument("--category", default="CONTROL_PLANE_TIME")
    p.add_argument("--work-class", default="NECESSARY")
    p.add_argument("--attempt", type=int, default=1)
    p.add_argument("--cache-hit", choices=("true","false","unknown"), default="unknown")
    p.add_argument("--input-file")
    p.add_argument("--input-fingerprint")
    p.add_argument("--output-artifact")
    p.add_argument("--status", default="PASS")
    args=p.parse_args()
    work_class=args.work_class.upper()
    if work_class not in WORK_CLASSES:
        raise SystemExit(f"invalid work class: {work_class}")
    args.state.parent.mkdir(parents=True, exist_ok=True)
    data=load(args.state)
    rec=data["stages"].setdefault(args.stage,{})
    if args.action=="start":
        rec.update({
            "stage":args.stage,
            "start":utcnow(),
            "started_monotonic_ns":time.monotonic_ns(),
            "category":args.category,
            "work_class":work_class,
            "status":"RUNNING",
            "attempt":max(1,args.attempt),
            "cache_hit":None if args.cache_hit=="unknown" else args.cache_hit=="true",
            "input_fingerprint":args.input_fingerprint or fingerprint(args.input_file),
            "output_artifact":args.output_artifact,
        })
    else:
        started=int(rec.get("started_monotonic_ns") or 0)
        if started <= 0:
            raise SystemExit(f"stage {args.stage} was not started")
        end_ns=time.monotonic_ns()
        end=utcnow()
        duration_ms=max(0.0,(end_ns-started)/1_000_000.0)
        rec.update({
            "end":end,
            "finished_monotonic_ns":end_ns,
            "duration_ms":round(duration_ms,3),
            "category":args.category or rec.get("category"),
            "work_class":work_class or rec.get("work_class"),
            "status":args.status,
            "attempt":max(1,args.attempt),
            "cache_hit":rec.get("cache_hit") if args.cache_hit=="unknown" else args.cache_hit=="true",
            "input_fingerprint":args.input_fingerprint or rec.get("input_fingerprint") or fingerprint(args.input_file),
            "output_artifact":args.output_artifact or rec.get("output_artifact"),
        })
        emit_performance_event(
            stage=args.stage,
            category=rec["category"],
            started_at=rec["start"],
            finished_at=end,
            duration_ms=duration_ms,
            success=args.status=="PASS",
            cache_hit=rec["cache_hit"],
            work_class=rec["work_class"],
            attempt=rec["attempt"],
            input_fingerprint=rec["input_fingerprint"],
            output_artifact=rec["output_artifact"],
            metadata={"source":"e2e_latency_stage"},
        )
        print(f"STAGE={args.stage}")
        print(f"STAGE_DURATION_MS={duration_ms:.3f}")
        print(f"WORK_CLASS={rec['work_class']}")
    args.state.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
