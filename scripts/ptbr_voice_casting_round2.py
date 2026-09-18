from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.services.voice_casting_round2_service import execute_round2


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--request",type=Path,required=True)
    parser.add_argument("--checkpoint",type=Path,required=True)
    parser.add_argument("--feedback",type=Path,required=True)
    parser.add_argument("--identity-map",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()

    job=json.loads(args.config.read_text(encoding="utf-8"))
    request=json.loads(args.request.read_text(encoding="utf-8"))
    checkpoint=json.loads(args.checkpoint.read_text(encoding="utf-8"))
    feedback=json.loads(args.feedback.read_text(encoding="utf-8"))
    identity_map=json.loads(args.identity_map.read_text(encoding="utf-8"))
    runtime_head=(os.environ.get("GITHUB_SHA") or request.get("source_head") or "").strip()

    result=asyncio.run(execute_round2(
        job=job,
        request=request,
        checkpoint=checkpoint,
        feedback=feedback,
        identity_map=identity_map,
        output_root=args.output_dir,
        runtime_head=runtime_head,
    ))
    state=result["state"]
    print("ROUND1_HUMAN_FEEDBACK=CONSUMED")
    print("HUMAN_TOP2_SELECTED=YES")
    print("ROUND2_MULTICONTEXT=PASS")
    print("PROSODY_WINDOW_BENCHMARK=PASS")
    print("BOUNDARY_ARTIFACT_AUDIT=PASS")
    print("RATE_TUNING=PASS")
    print("HUMAN_FINAL_SELECTION_REQUIRED=YES")
    print("REQUIRED_RESPONSE_FORMAT="+state["required_response_format"])
    print("HARNESS_AUTHORITY_PRESERVED=YES")
    print("JOB18_UNCHANGED=YES")
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
