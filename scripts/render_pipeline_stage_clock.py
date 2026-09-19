from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def _load(path: Path) -> dict:
    if not path.is_file():
        return {"version":"render-pipeline-stage-clock/v1","stages":{}}
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise SystemExit("stage clock must be an object")
    value.setdefault("stages",{})
    return value


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("start","end"))
    p.add_argument("stage")
    p.add_argument("--path",type=Path,default=Path("runtime/render/pipeline-stage-clock.json"))
    args=p.parse_args()
    args.path.parent.mkdir(parents=True,exist_ok=True)
    data=_load(args.path)
    stage=data["stages"].setdefault(args.stage,{})
    now=time.time()
    if args.action=="start":
        stage["started_at_epoch"]=now
        stage["status"]="RUNNING"
    else:
        started=float(stage.get("started_at_epoch") or 0.0)
        if started<=0:
            raise SystemExit(f"stage {args.stage} was not started")
        stage["finished_at_epoch"]=now
        stage["elapsed_seconds"]=max(0.0,now-started)
        stage["status"]="PASS"
    args.path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    if args.action=="end":
        print(f"STAGE_{args.stage.upper()}_SECONDS={stage['elapsed_seconds']:.6f}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
