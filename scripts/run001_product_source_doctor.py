#!/usr/bin/env python3
"""Read-only, GitHub Actions-friendly real RUN001 production input inventory."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.run001_owner_only_product_recovery import source_readiness


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--products-dir",type=Path,default=Path("products/run001"))
    ap.add_argument("--output",type=Path,required=True)
    opt=ap.parse_args()
    report=source_readiness(opt.products_dir)
    opt.output.parent.mkdir(parents=True,exist_ok=True)
    opt.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    for label in ("a","b"):
        row=report["video_"+label]
        print("RUN001_VIDEO_"+label.upper()+"_SCRIPT="+str(row["status"]))
        if "words" in row:
            print("RUN001_VIDEO_"+label.upper()+"_WORDS="+str(row["words"]))
    print("RUN001_DISTINCT_EDITORIAL="+report["distinct_editorial_scripts"])
    print("RUN001_HUMAN_OWNER_APPROVAL="+report["human_owner_approval"])
    print("RUN001_YOUTUBE_UPLOAD="+report["youtube_upload"])
    print("RUN001_DISPATCH_AUTHORIZED="+str(report["dispatch_authorized"]).upper())
    # Inventory succeeds as truthful diagnostics, never as an approval gate.
    return 0

if __name__=="__main__":
    raise SystemExit(main())
