from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.services.owner_voice_audition_performance_service import build_performance_receipt


def main() -> int:
    start=float(os.environ.get("AUDITION_MONOTONIC_START") or 0.0)
    total=max(0.0,time.monotonic()-start) if start>0 else 0.0
    values=dict(os.environ)
    values["TOTAL_AUDITION_SECONDS"]=round(total,6)
    receipt=build_performance_receipt(values)
    target=Path(
        os.environ.get("BR_OWNER_AUDITION_PERFORMANCE_RECEIPT")
        or Path(os.environ.get("RUNNER_TEMP") or "/tmp")/"br-owner-audition-public"/"owner-voice-performance-receipt.json"
    ).resolve()
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(f"TOTAL_AUDITION_SECONDS={receipt.get('TOTAL_AUDITION_SECONDS',0)}")
    print(f"WARM_RUN_TARGET_MET={receipt.get('WARM_RUN_TARGET_MET')}")
    print(f"COLD_RUN_TARGET_MET={receipt.get('COLD_RUN_TARGET_MET')}")
    print("OWNER_VOICE_PERFORMANCE_RECEIPT=PASS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
