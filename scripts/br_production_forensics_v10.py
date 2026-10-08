#!/usr/bin/env python3
"""Run a single owned MP4 production QA through the existing Harness authority."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.services.harness_capability_adapter import CapabilityAdapter
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.harness_routing_policy_service import HarnessRoutingRequest,route_harness_request
from app.services.reverse_engineering_harness_service import PRODUCTION_QA_CAPABILITY_ID


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="BR-no-GTA read-only media technical QA; never publication")
    p.add_argument("--authorization-id",required=True)
    p.add_argument("--owned-mp4",required=True)
    p.add_argument("--profile",choices=["synthetic_ci_canary","br_no_gta_1080p_master"],required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    output=Path(args.output)
    if (not output.is_absolute() or output.exists() or output.is_symlink()
        or output.suffix!=".json" or not output.parent.is_dir()):
        p.error("A new absolute private JSON receipt path is required")
    route=route_harness_request(HarnessRoutingRequest(
        intent="Analyze technical risks in one owned BR-no-GTA video candidate",
        authorized_action="RESEARCH",domain="production-media-quality",
        required_capability_id=PRODUCTION_QA_CAPABILITY_ID,
        provider_required=False,fallback_allowed=False,learning_required=False,
    ))
    execution=CapabilityAdapter().execute(
        authorization=args.authorization_id,
        task_envelope=TaskEnvelope(
            task_id=f"production-forensics-v10-{os.getpid()}",
            capability_id=PRODUCTION_QA_CAPABILITY_ID,
            action="RESEARCH",objective="Inspect authorized video for technical delivery blockers",
            allowed_tools=("ffprobe","ffmpeg"),cost_budget=0.0,retry_budget=0,
        ),
        routing_decision=route,
        payload={"source_path":args.owned_mp4,"profile":args.profile,"rights":"owned"},
    )
    fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as out:
        json.dump(execution.to_dict(),out,ensure_ascii=False,sort_keys=True,indent=2)
        out.write("\n")
    result=execution.result
    print("BR_V10_REAL_MP4_QA="+result["technical_status"])
    print("BR_V10_OWNER_VOICE_IDENTITY=NOT_VERIFIED")
    print("BR_V10_PUBLICATION_AUTHORIZED=FALSE")
    return 0 if result["technical_status"]=="TECHNICAL_SAMPLED_QA_PASS" else 3


if __name__=="__main__":
    raise SystemExit(main())
