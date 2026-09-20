from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.services.video_a_script_quality import validate_script_quality

PACKAGE_PATH=Path("content/research/video-a-extended-look-editorial-package-v2.json")


def load(path:Path)->Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--audit",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=True)

    draft=load(PACKAGE_PATH)
    audit=load(args.audit)
    evidence={str(x.get("FINDING_ID")):x for x in audit.get("findings") or []}
    if audit.get("status")!="PASS":
        raise RuntimeError("primary-source audit did not pass")
    if len(evidence)<25:
        raise RuntimeError("primary-source evidence map is too small")

    required={
        str(ref)
        for section in (draft.get("script") or {}).get("sections") or []
        for ref in section.get("evidence_ids") or []
    }
    missing=sorted(required-set(evidence))
    if missing:
        raise RuntimeError("script references missing primary evidence: "+",".join(missing))

    package={
        **draft,
        "primary_source":audit.get("source"),
        "evidence_map":[evidence[key] for key in sorted(evidence)],
        "EXTENDED_LOOK_FINDINGS_TOTAL":audit.get("EXTENDED_LOOK_FINDINGS_TOTAL"),
        "HIGH_VALUE_NEW_FINDINGS":audit.get("HIGH_VALUE_NEW_FINDINGS"),
        "EDITORIAL_NOVELTY":str(draft.get("editorial_novelty") or "PENDING"),
    }
    qa=validate_script_quality(package)
    package["script_qa"]=qa
    package["SCRIPT_HUMAN_REVIEW"]="PENDING"
    package["HUMAN_VOICE_REVIEW"]="REJECTED"
    package["PRODUCTION_READINESS"]="FAIL"
    package["FULL_RENDER_AUTHORIZED"]="NO"
    package["YOUTUBE_PUBLICATION"]="NO"

    # Script can go to human review only when objective QA passes. This never
    # converts human review into approval.
    if qa["SCRIPT_EDITORIAL_QUALITY"]!="PASS":
        raise RuntimeError("SCRIPT_EDITORIAL_QUALITY=FAIL: "+json.dumps(qa,ensure_ascii=False))

    outline=[
        {
            "order":index+1,
            "section_id":section.get("section_id"),
            "heading":section.get("heading"),
            "evidence_ids":section.get("evidence_ids") or [],
            "audience_value":section.get("audience_value"),
        }
        for index,section in enumerate((draft.get("script") or {}).get("sections") or [])
    ]
    script_txt="\n\n".join(
        f"{section.get('heading')}\n\n{section.get('narration')}"
        for section in (draft.get("script") or {}).get("sections") or []
    )+"\n"

    (args.output_dir/"video-a-editorial-package.json").write_text(
        json.dumps(package,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    (args.output_dir/"evidence-map.json").write_text(
        json.dumps(package["evidence_map"],ensure_ascii=False,indent=2),encoding="utf-8"
    )
    (args.output_dir/"editorial-angles.json").write_text(
        json.dumps(draft.get("angles") or [],ensure_ascii=False,indent=2),encoding="utf-8"
    )
    (args.output_dir/"outline.json").write_text(
        json.dumps(outline,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    (args.output_dir/"script-ptbr.txt").write_text(script_txt,encoding="utf-8")
    (args.output_dir/"script-qa.json").write_text(
        json.dumps(qa,ensure_ascii=False,indent=2),encoding="utf-8"
    )

    print("EXTENDED_LOOK_FINDINGS_TOTAL="+str(package["EXTENDED_LOOK_FINDINGS_TOTAL"]))
    print("HIGH_VALUE_NEW_FINDINGS="+str(package["HIGH_VALUE_NEW_FINDINGS"]))
    print("SCRIPT_WORD_COUNT="+str(qa["SCRIPT_WORD_COUNT"]))
    print("META_PRODUCTION_LEAKAGE="+str(qa["META_PRODUCTION_LEAKAGE"]))
    print("INTERNAL_QA_LANGUAGE_IN_SCRIPT="+str(qa["INTERNAL_QA_LANGUAGE_IN_SCRIPT"]))
    print("UNSUPPORTED_CLAIMS="+str(qa["UNSUPPORTED_CLAIMS"]))
    print("INFORMATION_DENSITY_STATUS="+str(qa["INFORMATION_DENSITY"]))
    print("SCRIPT_EDITORIAL_QUALITY="+str(qa["SCRIPT_EDITORIAL_QUALITY"]))
    print("SCRIPT_HUMAN_REVIEW=PENDING")
    print("HUMAN_VOICE_REVIEW=REJECTED")
    print("FULL_RENDER_AUTHORIZED=NO")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
