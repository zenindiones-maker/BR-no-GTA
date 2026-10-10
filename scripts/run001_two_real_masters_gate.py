#!/usr/bin/env python3
"""Two independent real 25-minute masters gate, before either PRIVATE upload.

This is one stage of the existing Harness mission, not a release authorization.
Requires both actual MP4s; will not accept two names pointing to one movie.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from production_25min_master_gate import inspect, MasterGateError, OUTPUT_SCHEMA

_TWO_SCHEMA = "BRRun001TwoDistinctMasters25Min/v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")


def verify_both(a: Path, b: Path) -> dict:
    pa = inspect(a, "A")  # independently ffprobes actual bytes, then hashes
    pb = inspect(b, "B")
    for expected, r in (("A", pa), ("B", pb)):
        if r.get("schema") != OUTPUT_SCHEMA or r.get("case") != expected or r.get("status") != "PASS":
            raise MasterGateError("RUN001_INDIVIDUAL_MASTER_INCOMPLETE")
        if not _SHA.fullmatch(str(r.get("media_sha256") or "")):
            raise MasterGateError("RUN001_REAL_MASTER_HASH_INVALID")
        if not 24 <= float(r["media"]["duration_minutes"]) <= 26:
            raise MasterGateError("RUN001_DURATION_OUT_OF_RANGE")
        if r.get("production_release_authorized") is not False:
            raise MasterGateError("RUN001_UNAUTHORIZED_RELEASE_FLAG")
    if pa["media_sha256"] == pb["media_sha256"]:
        raise MasterGateError("RUN001_DUPLICATE_VIDEO_A_AND_VIDEO_B_FORBIDDEN")
    return {
        "schema": _TWO_SCHEMA,
        "status": "PASS",
        "video_a": pa,
        "video_b": pb,
        "distinct_master_bytes": True,
        "editorial_uniqueness": "REQUIRES_SEPARATE_QA",
        "br_owner_voice_approved": "REQUIRES_INDEPENDENT_HUMAN_LEDGER_READBACK",
        "private_hd_youtube_ids": [],
        "telegram_human_review": "NOT_DELIVERED",
        "public_release_authorized": False,
    }


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--master-a", type=Path, required=True)
    parser.add_argument("--master-b", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    v=parser.parse_args()
    try:
        result=verify_both(v.master_a,v.master_b)
    except (ValueError,OSError) as exc:
        result={"schema":_TWO_SCHEMA,"status":"FAIL",
                "failure_class":type(exc).__name__,"error":str(exc)[:160],
                "public_release_authorized":False}
    v.receipt.parent.mkdir(parents=True, exist_ok=True)
    v.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("RUN001_TWO_REAL_25MIN_MASTERS="+result["status"])
    print("NO_AUTOMATIC_YOUTUBE_PUBLICATION=PASS")
    return 0 if result["status"]=="PASS" else 1


if __name__=="__main__":
    raise SystemExit(main())
