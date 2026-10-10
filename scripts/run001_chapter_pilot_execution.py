"""Run a non-publishing chapter pilot from an explicit, locally materialized EDL.

This runner never fabricates media, rights clearance, narration or semantic approval.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from app.services.run001_script_to_screen_frame_evidence import collect_frame_evidence
from scripts.run001_script_to_screen_pilot import render_pilot

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--edl",required=True,type=Path)
    parser.add_argument("--out-dir",required=True,type=Path)
    args=parser.parse_args()
    edl=json.loads(args.edl.read_text(encoding="utf-8"))
    out=args.out_dir
    out.mkdir(parents=True,exist_ok=True)
    master=out/"chapter-pilot.mp4"
    pilot=render_pilot(edl,master)
    frames=collect_frame_evidence(edl,master,out/"frames")
    (out/"pilot-receipt.json").write_text(json.dumps(pilot,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    (out/"frame-evidence.json").write_text(json.dumps(frames,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print("CHAPTER_PILOT_TECHNICAL=PASS")
    print("EDITORIAL_SEMANTIC_QA=PENDING")
    print("OWNER_VOICE_HUMAN_APPROVAL=PENDING")
    print("YOUTUBE_UPLOAD=BLOCKED")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
