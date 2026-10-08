#!/usr/bin/env python3
"""Fresh original-video baseline + verified, read-only failure triage V20."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.services.br_specialist_verified_experience_v20 import assess_experience
from scripts.br_specialist_router_benchmark_v19 import run as routing_benchmark
from scripts.br_specialist_benchmark_v17 import benchmark as original_visual_benchmark


def run(*,root:Path,output:Path)->dict:
    if (not root.is_absolute() or not root.is_dir() or root.is_symlink()
        or not output.is_absolute() or output.exists() or output.suffix!=".json"
        or not output.parent.is_dir()):
        raise ValueError("SPECIALIST_V20_PRIVATE_OUTPUT_SCOPE_INVALID")
    t0=perf_counter()
    routing=routing_benchmark(
        root=Path(__file__).resolve().parents[1],
        output=root/"br-v20-routing-source-private.json",
    )
    visual=original_visual_benchmark(
        root=root,
        output=root/"br-v20-visual-source-private.json",
    )
    report=assess_experience(routing,visual)
    report["measured_total_wall_seconds"]=round(perf_counter()-t0,4)
    from app.services.br_specialist_verified_experience_v20 import _digest
    report["receipt_sha256"]=_digest({k:v for k,v in report.items() if k!="receipt_sha256"})
    fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(report,f,sort_keys=True,ensure_ascii=False,indent=2)
        f.write("\n")
    return report


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    r=run(root=Path(args.root),output=Path(args.output))
    print(f"BR_V20_ROUTER_VERIFIED={r['router_correct']}/{r['router_trials']}")
    print(f"BR_V20_ACTUAL_VISUAL_VERIFIED={r['av_correct']}/{r['av_trials']}")
    print(f"BR_V20_DETERMINISTIC_BASELINE={r['status']}")
    print(f"BR_V20_NEW_SLM_VERIFIED={r['professional_slm_verified']}")
    print(f"BR_V20_OWNED_EPISODE_VERIFIED=FALSE")
    print(f"BR_V20_VOICE_ACTIVATED=FALSE")
    raise SystemExit(0 if r["status"]=="CONTROLLED_BASELINE_VERIFIED" else 3)
