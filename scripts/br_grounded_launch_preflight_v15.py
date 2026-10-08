#!/usr/bin/env python3
"""Offline launch preflight; no network, voice I/O, training or publication."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from app.services.br_grounded_launch_preflight_v15 import build_grounded_launch_preflight


def _read_private_json(path: Path) -> dict:
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
        or path.stat().st_size>512_000):
        raise ValueError("LAUNCH_EVIDENCE_PRIVATE_ABSOLUTE_REGULAR_FILE_REQUIRED")
    with path.open(encoding="utf-8") as source:
        value=json.load(source)
    if not isinstance(value,dict):
        raise ValueError("LAUNCH_EVIDENCE_JSON_OBJECT_REQUIRED")
    return value


def main(args: list[str]|None=None) -> int:
    p=argparse.ArgumentParser(
        description="Read-only BR-no-GTA launch reality audit (always denies promotion).")
    p.add_argument("--ledger-head",required=True,type=Path)
    p.add_argument("--llama-policy",default="config/llamafactory_admission_v13.json",
                   type=Path)
    p.add_argument("--latest-run-id",type=int)
    p.add_argument("--latest-failure",choices=[
        "LEDGER_FAST_FORWARD_PUSH_REJECTED","RUNNER_SHUTDOWN","NONE"])
    p.add_argument("--media-evidence",type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args(args)
    if (a.latest_run_id is None)!=(a.latest_failure is None):
        p.error("--latest-run-id and --latest-failure must be supplied together")
    out=a.out
    if (not out.is_absolute() or out.is_symlink() or out.exists()
        or not out.parent.is_dir()):
        p.error("--out must be a new private absolute JSON path")
    try:
        policy=json.loads(a.llama_policy.read_text(encoding="utf-8"))
        report=build_grounded_launch_preflight(
            ledger_head=_read_private_json(a.ledger_head),
            llama_policy=policy,
            latest_attempt=(
                {"run_id":a.latest_run_id,"failure_class":a.latest_failure}
                if a.latest_run_id is not None else None
            ),
            media_evidence=_read_private_json(a.media_evidence)
                if a.media_evidence is not None else None,
        )
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        # Do not print raw private ledger data, user paths or JSON contents.
        print("BR_V15_PREFLIGHT_INPUT_OR_POLICY=BLOCKED",file=sys.stderr)
        return 2
    fd=os.open(out,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(report,f,sort_keys=True,ensure_ascii=False,indent=2)
            f.write("\n")
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    print("BR_V15_LIVE_OPERATIONS_ATTEMPTED=FALSE")
    print("BR_V15_OWNER_VOICE_GATE="+report["ledger_head"]["identity_gate_reported"])
    print("BR_V15_TELEGRAM_REPORTED_SEND="+str(report["ledger_head"]["telegram_delivery_reported"]).upper())
    print("BR_V15_LLAMAFACTORY_TRAINING_READY=FALSE")
    print("BR_V15_RELEASE_AUTHORIZATION=FORBIDDEN")
    print("BR_V15_BLOCKER_COUNT="+str(len(report["blockers"])))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
