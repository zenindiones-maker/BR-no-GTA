"""Diagnose real chapter production inputs without inventing approval or media."""
from __future__ import annotations
import json
from pathlib import Path
from app.services.run001_owner_voice_admission_service import require_owner_voice_admission, OwnerVoiceAdmissionBlocked

def audit_chapter_inputs(request: dict, script: dict, assets: dict) -> dict:
    blockers=[]
    if str(request.get("final_voice","")).strip().lower() in ("voice b","thalita"):
        blockers.append("LEGACY_VOICE_B_REQUEST")
    try:
        require_owner_voice_admission(request)
    except OwnerVoiceAdmissionBlocked as exc:
        blockers.append(str(exc))
    if not isinstance(script.get("segments"),list) or not script["segments"]:
        blockers.append("TIMED_NARRATION_SEGMENTS_MISSING")
    if not isinstance(assets,dict) or not assets:
        blockers.append("MATERIALIZED_EDITORIAL_MEDIA_MISSING")
    else:
        for asset_id,asset in assets.items():
            if not isinstance(asset,dict) or asset.get("rights_status")!="CLEARED":
                blockers.append("MEDIA_RIGHTS_NOT_CLEARED:"+str(asset_id))
            elif not isinstance(asset.get("path"),str) or not Path(asset["path"]).is_file():
                blockers.append("MEDIA_NOT_MATERIALIZED:"+str(asset_id))
    return {"schema":"BRChapterInputDiagnostic/v1","status":"BLOCKED" if blockers else "INPUTS_PRESENT_REQUIRES_INDEPENDENT_VERIFICATION","blockers":blockers,"human_voice_approval":"NOT_ESTABLISHED_BY_DIAGNOSTIC","editorial_rights":"NOT_ESTABLISHED_BY_DIAGNOSTIC","render_authorized":False,"youtube_upload_authorized":False}

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--request",type=Path,required=True)
    p.add_argument("--script",type=Path,required=True)
    p.add_argument("--assets",type=Path,required=True)
    args=p.parse_args()
    result=audit_chapter_inputs(json.loads(args.request.read_text()),json.loads(args.script.read_text()),json.loads(args.assets.read_text()))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if result["status"]=="BLOCKED" else 0

if __name__=="__main__":
    raise SystemExit(main())
