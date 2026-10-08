#!/usr/bin/env python3
"""Run one bounded authorized studio observation, never a production job."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.reverse_engineering_harness_service import STUDIO_CAPABILITY_ID


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Harness-approved media studio read-only measurements")
    parser.add_argument("--authorization-id",required=True)
    parser.add_argument("--mode",required=True,choices=["stems","alignment","motion","timeline"])
    parser.add_argument("--input",action="append",required=True,help="Absolute approved file. Repeat for stems.")
    parser.add_argument("--rights",required=True,choices=["owned","licensed"])
    parser.add_argument("--window-seconds",type=int)
    parser.add_argument("--max-frames",type=int)
    parser.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    target=Path(args.output).expanduser()
    if (not target.is_absolute() or target.exists() or target.is_symlink()
        or not target.parent.is_dir()):
        parser.error("output must be a new absolute file in an existing private directory")
    options={}
    if args.window_seconds is not None:
        if args.mode!="stems":
            parser.error("--window-seconds only valid for stems")
        options["window_seconds"]=args.window_seconds
    if args.max_frames is not None:
        if args.mode!="motion":
            parser.error("--max-frames only valid for motion")
        options["max_frames"]=args.max_frames
    decision=route_harness_request(HarnessRoutingRequest(
        intent=f"Evidence-only studio {args.mode} study",
        authorized_action="RESEARCH", required_capability_id=STUDIO_CAPABILITY_ID,
        domain="studio-forensics",fallback_allowed=False,
        provider_required=False,learning_required=False,
    ))
    result=CapabilityAdapter().execute(
        authorization=args.authorization_id,
        task_envelope=TaskEnvelope(
            task_id=f"studio-v6-{os.getpid()}",capability_id=STUDIO_CAPABILITY_ID,
            action="RESEARCH", objective="Measure approved original media only",
            allowed_tools=("ffmpeg","ffprobe"),cost_budget=0.0,retry_budget=0,
        ),
        routing_decision=decision,
        payload={"mode":args.mode,"rights":args.rights,
                 "inputs":args.input,"options":options},
    )
    serialized=json.dumps(result.to_dict(),ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    flags=os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd=os.open(str(target),flags,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as out:
        out.write(serialized)
    print("BR_STUDIO_V6_EVIDENCE=PASS")
    print("BR_STUDIO_V6_PRODUCTION_MUTATION=FALSE")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
