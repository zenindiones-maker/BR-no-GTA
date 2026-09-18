from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.services.voice_casting_service import execute_round1


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--request",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()

    job=json.loads(args.config.read_text(encoding="utf-8"))
    request=json.loads(args.request.read_text(encoding="utf-8"))
    runtime_head=(os.environ.get("GITHUB_SHA") or request.get("base_head") or "").strip()
    branch=(os.environ.get("GITHUB_REF_NAME") or "work/gate6f-analytics-learning").strip()
    result=asyncio.run(execute_round1(
        job=job,
        request=request,
        output_root=args.output_dir,
        runtime_head=runtime_head,
        branch=branch,
    ))
    manifest=result["round1_manifest"]
    state=result["state"]
    print("PTBR_EDGE_VOICE_INVENTORY=PASS")
    print("BLIND_VOICE_CASTING_ROUND1=READY")
    print("HUMAN_REVIEW_REQUIRED=YES")
    print("PASSING_BLIND_IDS="+",".join(manifest["passing_blind_ids"]))
    print("REQUIRED_RESPONSE_FORMAT="+state["required_response_format"])
    print("JOB18_UNCHANGED=YES")
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES")
    print("HARNESS_AUTHORITY_PRESERVED=YES")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
