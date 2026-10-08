#!/usr/bin/env python3
"""Single permitted local Iris camera shot through the existing Harness."""
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
from app.services.reverse_engineering_harness_service import IRIS_CAPABILITY_ID


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description="Capture authorized owned static HTML only")
    parser.add_argument("--authorization-id",required=True)
    parser.add_argument("--input",required=True,help="Absolute approved .html file")
    parser.add_argument("--output-image",required=True,help="New private .png path")
    parser.add_argument("--output-receipt",required=True,help="New private .json path")
    parser.add_argument("--viewport",choices=("960x600","390x844"),default="960x600")
    parser.add_argument("--selector",default=None)
    args=parser.parse_args(argv)
    receipt=Path(args.output_receipt)
    if (not receipt.is_absolute() or receipt.suffix!=".json"
        or receipt.exists() or receipt.is_symlink() or not receipt.parent.is_dir()):
        parser.error("receipt must be new absolute JSON path under a private directory")
    route=route_harness_request(HarnessRoutingRequest(
        intent="Capture a trusted local owned static HTML page through pinned Iris",
        authorized_action="RESEARCH",required_capability_id=IRIS_CAPABILITY_ID,
        domain="web-visual-observation",fallback_allowed=False,
        provider_required=False,learning_required=False,
    ))
    result=CapabilityAdapter().execute(
        authorization=args.authorization_id,
        task_envelope=TaskEnvelope(
            task_id=f"iris-v7-{os.getpid()}",capability_id=IRIS_CAPABILITY_ID,
            action="RESEARCH",objective="Private local visual observation only",
            allowed_tools=("iris","chromium"),cost_budget=0.0,retry_budget=0,
        ),
        routing_decision=route,
        payload={"source_path":args.input,"output_path":args.output_image,
                 "rights":"owned","viewport":args.viewport,"selector":args.selector},
    )
    data=json.dumps(result.to_dict(),ensure_ascii=False,sort_keys=True,indent=2)+"\n"
    fd=os.open(receipt,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as out:
        out.write(data)
    print("BR_IRIS_HARNESS_LOCAL_VISUAL_EVIDENCE=PASS")
    print("BR_IRIS_LIVE_NETWORK=FORBIDDEN")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
