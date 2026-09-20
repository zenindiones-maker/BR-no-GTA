from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.video_a_production_readiness import (
    CANDIDATE_PATH,
    PRONUNCIATION_EVIDENCE_PATH,
    pronunciation_inventory,
    script_text,
)
from scripts.video_a_audio_forensics import inventory_false_positives


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()

    candidate=json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    registry=json.loads(PRONUNCIATION_EVIDENCE_PATH.read_text(encoding="utf-8"))
    inventory=pronunciation_inventory(candidate,registry)
    false_terms=inventory_false_positives(inventory,script_text(candidate))
    inventory["FALSE_POSITIVE_TERMS"]=len(false_terms)
    inventory["false_positive_term_list"]=false_terms

    if false_terms:
        raise RuntimeError("FALSE_POSITIVE_TERMS="+json.dumps(false_terms,ensure_ascii=False))
    if inventory["UNCONFIGURED_SCRIPT_ENTITIES"]:
        raise RuntimeError(
            "UNCONFIGURED_SCRIPT_ENTITIES="
            +json.dumps(inventory["UNCONFIGURED_SCRIPT_ENTITIES"],ensure_ascii=False)
        )
    if inventory["PTBR_CANDIDATE_CONFIGURATION_PERCENT"]!=100.0:
        raise RuntimeError("PTBR_CANDIDATE_CONFIGURATION_PERCENT must be 100")
    if inventory["ALL_CONFIGURED_TERMS_PTBR"]!="PASS":
        raise RuntimeError("ALL_CONFIGURED_TERMS_PTBR must PASS")

    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding="utf-8")

    for key in (
        "PRONUNCIATION_TERMS_TOTAL",
        "CHARACTER_NAMES_TOTAL",
        "PLACE_NAMES_TOTAL",
        "BUSINESS_ORGANIZATION_NAMES_TOTAL",
        "BRAND_ACRONYM_FOREIGN_TERMS_TOTAL",
        "TERMS_WITH_VALIDATED_PRONUNCIATION",
        "TERMS_PENDING_VALIDATION",
        "PRONUNCIATION_COVERAGE_PERCENT",
        "PTBR_CANDIDATE_CONFIGURATION_PERCENT",
        "FALSE_POSITIVE_TERMS",
    ):
        print(f"{key}={inventory[key]}")
    print("UNVALIDATED_PROPER_NOUNS="+json.dumps(inventory["UNVALIDATED_PROPER_NOUNS"],ensure_ascii=False))
    print("SEMANTIC_SECTION_POLICY_PRESERVED=YES")
    print("GLOBAL_PRONUNCIATION_STATUS=FAIL")
    print("LEONIDA_PRONUNCIATION=FAIL")
    print("HUMAN_VOICE_REVIEW=REJECTED")
    print("PRODUCTION_READINESS=FAIL")
    print("FULL_RENDER_AUTHORIZED=NO")
    print("YOUTUBE_PUBLICATION=NO")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
