#!/usr/bin/env python3
"""One authorized REA/Ghidra static function inspection of a local owned ELF."""
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
from app.services.reverse_engineering_harness_service import NATIVE_CAPABILITY_ID


def main(argv=None):
    p=argparse.ArgumentParser(description="Pinned Ghidra function Evidence, owner-built ELF only")
    p.add_argument("--authorization-id",required=True)
    p.add_argument("--owned-elf",required=True)
    p.add_argument("--function",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    path=Path(args.output)
    if (not path.is_absolute() or path.exists() or path.is_symlink()
        or not path.parent.is_dir() or path.suffix!=".json"):
        p.error("--output must be a new absolute private JSON path")
    route=route_harness_request(HarnessRoutingRequest(
        intent="Inspect one owner-built ELF function using pinned REA/Ghidra",
        authorized_action="RESEARCH",required_capability_id=NATIVE_CAPABILITY_ID,
        domain="native-binary-forensics",fallback_allowed=False,
        provider_required=False,learning_required=False,
    ))
    result=CapabilityAdapter().execute(
        authorization=args.authorization_id,
        task_envelope=TaskEnvelope(
            task_id=f"rea-ghidra-v9-{os.getpid()}",capability_id=NATIVE_CAPABILITY_ID,
            action="RESEARCH",objective="Investigate one scoped original ELF function without executing it",
            allowed_tools=("rea","ghidra"),cost_budget=0.0,retry_budget=0,
        ),
        routing_decision=route,
        payload={"source_path":args.owned_elf,"rights":"owned","function":args.function},
    )
    fd=os.open(path,os.O_EXCL|os.O_CREAT|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(result.to_dict(),f,ensure_ascii=False,sort_keys=True,indent=2)
        f.write("\n")
    print("BR_V9_HARNESS_NATIVE_GHIDRA_FUNCTION_EVIDENCE=PASS")
    print("BR_V9_TARGET_BINARY_EXECUTED_BY_ANALYZER=FALSE")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
