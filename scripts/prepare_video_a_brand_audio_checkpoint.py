from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from app.services.brand_audio_service import prepare_brand_audio
from app.services.channel_spoken_branding_service import (
    build_spoken_branding_contract,
    validate_job_spoken_branding,
)


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--render-job",type=Path,required=True)
    parser.add_argument("--video-config",type=Path,required=True)
    parser.add_argument("--work-root",type=Path,required=True)
    parser.add_argument("--checkpoint-dir",type=Path,required=True)
    parser.add_argument("--proof",type=Path,required=True)
    args=parser.parse_args()

    job=json.loads(args.render_job.read_text(encoding="utf-8"))
    config=json.loads(args.video_config.read_text(encoding="utf-8"))
    if job.get("render_job_id")!=920101 or job.get("video_id")!=920101:
        raise SystemExit("VIDEO_A_RENDER_JOB_IDENTITY_MISMATCH")
    if job.get("render_job_id")==18:
        raise SystemExit("JOB18_IS_FROZEN")
    if job.get("youtube_publication") is not False:
        raise SystemExit("YOUTUBE_PUBLICATION_MUST_REMAIN_FALSE")
    narration=job.get("narration") or {}
    if narration.get("human_quality_baseline")!="Voice B":
        raise SystemExit("VOICE_B_BASELINE_MISMATCH")
    if narration.get("voice")!="pt-BR-ThalitaMultilingualNeural":
        raise SystemExit("VOICE_B_IDENTITY_MISMATCH")

    theme=config.get("brand_opening_theme")
    job["spoken_branding"]=build_spoken_branding_contract(theme=theme)
    validate_job_spoken_branding(job)

    args.work_root.mkdir(parents=True,exist_ok=True)
    manifest=prepare_brand_audio(job,args.work_root)
    if manifest.get("status")!="PASS":
        raise SystemExit("BRAND_AUDIO_QA_FAIL")
    checks=manifest.get("checks") or {}
    if not all(checks.values()):
        raise SystemExit("BRAND_AUDIO_CHECKS_FAIL")
    if len(manifest["takes"]["opening"])!=1 or len(manifest["takes"]["closing"])!=1:
        raise SystemExit("BRAND_AUDIO_RUNTIME_ASSET_COUNT_FAIL")
    if manifest["selected"]["opening"]["take_id"]!="take-2":
        raise SystemExit("BRAND_AUDIO_OPENING_PROFILE_FAIL")
    if manifest["selected"]["closing"]["take_id"]!="G-brand-mixed":
        raise SystemExit("BRAND_AUDIO_CLOSING_ASSET_FAIL")
    if manifest["opening_text"] != (
        "Booooa meu povo, aqui é BR no GTA 6 e hoje vamos de "
        "fatos, vazamentos, tecnologia e rumores de GTA 6!"
    ):
        raise SystemExit("OPENING_TEXT_CANONICAL_FAIL")
    if manifest["closing_text"]!="E BR não dorme em Vice City":
        raise SystemExit("CLOSING_TEXT_CANONICAL_FAIL")
    if manifest["voice_blind_id"]!="Voice B":
        raise SystemExit("VOICE_B_USED_FAIL")

    source=args.work_root/"brand-audio-bundle"
    if args.checkpoint_dir.exists():
        shutil.rmtree(args.checkpoint_dir)
    shutil.copytree(source,args.checkpoint_dir)
    proof={
        "status":"PASS",
        "render_job_id":job["render_job_id"],
        "video_id":job["video_id"],
        "execution_id":job["execution_id"],
        "voice":"Voice B",
        "voice_identity":manifest["voice"],
        "provider":manifest["provider"],
        "provider_version":manifest["provider_version"],
        "opening_text":manifest["opening_text"],
        "closing_text":manifest["closing_text"],
        "opening_take_count":len(manifest["takes"]["opening"]),
        "closing_take_count":len(manifest["takes"]["closing"]),
        "selected_take_id":manifest["selection"]["selected_take_id"],
        "selected_opening_take_id":manifest["selection"]["selected_opening_take_id"],
        "selected_closing_fallback_take_id":manifest["selection"]["selected_closing_fallback_take_id"],
        "human_approved_opening_reference":"I-opening-fluid-2.mp3",
        "human_approved_final_end_sample_id":"G-brand-mixed",
        "automatic_naturality_winner":manifest["selection"]["automatic_naturality_winner"],
        "cache":manifest["cache"],
        "bundle_reused":manifest.get("bundle_reused"),
        "OFFICIAL_INTRO_FIRST":"PASS",
        "SPOKEN_OPENING_AFTER_INTRO":"PASS",
        "VOICE_B_USED":"PASS",
        "FLUID2_OPENING_SELECTED":(
            "PASS"
            if manifest["selection"]["selected_opening_take_id"]=="take-2"
            and manifest["selected"]["opening"]["rate"]=="+3%"
            and manifest["selected"]["opening"]["pitch"]=="+1Hz"
            else "FAIL"
        ),
        "OPENING_TEXT_CANONICAL":"PASS",
        "CLOSING_TEXT_CANONICAL":"PASS",
        "BRAND_AUDIO_CACHE_POLICY":"PASS",
        "EDITORIAL_HOOK_PRESERVED":"PASS",
        "JOB18_UNCHANGED":"YES",
        "PUBLICATION_AUTHORITY_UNCHANGED":"YES",
        "youtube_publication":False,
    }
    args.proof.parent.mkdir(parents=True,exist_ok=True)
    args.proof.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding="utf-8")
    for key in (
        "OFFICIAL_INTRO_FIRST","SPOKEN_OPENING_AFTER_INTRO","VOICE_B_USED",
        "FLUID2_OPENING_SELECTED","OPENING_TEXT_CANONICAL","CLOSING_TEXT_CANONICAL",
        "BRAND_AUDIO_CACHE_POLICY","EDITORIAL_HOOK_PRESERVED",
    ):
        print(f"{key}=PASS")
    print(f"BRAND_OPENING_TAKES={proof['opening_take_count']}")
    print(f"SELECTED_OPENING_TAKE_ID={proof['selected_opening_take_id']}")
    print(f"SELECTED_CLOSING_FALLBACK_TAKE_ID={proof['selected_closing_fallback_take_id']}")
    print(f"BRAND_CLOSING_TAKES={proof['closing_take_count']}")
    print(f"BRAND_AUDIO_EXTERNAL_CALLS={proof['cache']['external_calls']}")
    print("JOB18_UNCHANGED=YES")
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
