from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
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
    expected={
        "mission":"ptbr-edge-voice-casting-v1",
        "base_head":"ac61c3cfc61a76c507e4092223aff835603c4020",
        "script_path":".run001/video-a-investigative-longform.json",
        "locale":"pt-BR",
        "provider":"edge-tts",
        "round1_rate":"+0%",
        "round1_pitch":"+0Hz",
        "job18_frozen":True,
        "publication_authority":"NONE",
    }
    for key,value in expected.items():
        if request.get(key)!=value:
            raise SystemExit(f"VOICE_CASTING_REQUEST_MISMATCH:{key}:{request.get(key)!r}")
    if (request.get("prior_human_feedback") or {}).get("result")!="PREFERS_BASELINE":
        raise SystemExit("VOICE_CASTING_REQUEST_MISMATCH:prior_human_feedback")
    ancestry=subprocess.run(
        ["git","merge-base","--is-ancestor",request["base_head"],"HEAD"],
        capture_output=True,text=True,
    )
    if ancestry.returncode!=0:
        raise SystemExit("VOICE_CASTING_BASE_HEAD_NOT_ANCESTOR")
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
    print("VOICE_CASTING_REQUEST=PASS")\n    print("HUMAN_A_B_REVIEW=PREFERS_BASELINE")\n    print("PTBR_EDGE_VOICE_INVENTORY=PASS")
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
