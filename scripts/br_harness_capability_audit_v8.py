#!/usr/bin/env python3
"""Offline Harness inventory audit; does not authorize, schedule or execute apps."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_capability_utilization_v8 import (
    probe_rea_discovery, capability_utilization_report,
)


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description="Read-only capability availability inventory")
    p.add_argument("--rea-bin",help="Existing explicitly pinned REA executable")
    p.add_argument("--output",required=True,help="New absolute private evidence file")
    args=p.parse_args(argv)
    dest=Path(args.output)
    if (not dest.is_absolute() or dest.exists() or dest.is_symlink()
        or not dest.parent.is_dir() or dest.suffix!=".json"):
        p.error("evidence must be new absolute private JSON")
    discovery=probe_rea_discovery(args.rea_bin) if args.rea_bin else None
    result=capability_utilization_report(registry=GLOBAL_CAPABILITY_REGISTRY,rea_probe=discovery)
    fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as out:
        json.dump(result,out,ensure_ascii=False,sort_keys=True,indent=2)
        out.write("\n")
    print("BR_CAPABILITY_REGISTRY_AUDITED=PASS")
    print(f"BR_CAPABILITY_REGISTERED_COUNT={result['registry_total']}")
    print(f"BR_CAPABILITY_EXECUTOR_DECLARED_COUNT={result['declared_executor_count']}")
    print("BR_CAPABILITY_EXPLICIT_RUNTIME_PROOFS_THIS_AUDIT=0")
    if discovery:
        for key,info in discovery["catalog"].items():
            print(f"BR_REA_{key.upper()}_DISCOVERY={info['readiness']}")
            print(f"BR_REA_{key.upper()}_NAMES_REPORTED={len(info['catalog_identifiers'])}")
        print("BR_REA_NATIVE_PROVIDER_ATTESTED=FALSE")
    print("BR_CAPABILITY_NO_PROMOTION=PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
