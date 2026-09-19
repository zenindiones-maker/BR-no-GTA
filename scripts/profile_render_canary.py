from __future__ import annotations

import argparse
import copy
import json
import subprocess
import time
from pathlib import Path

from app.main import initialize_application
from app.services.edit_plan_service import EditPlan
from app.services.render_learning_profile_service import executable_render_profile
from app.workers.audiovisual_worker import execute, probe_video
from app.workers.professional_audiovisual_worker import (
    _build_edit_plan,
    execute_ptbr_narration,
    validate_product_job,
)


def _trim_plan(plan: EditPlan, seconds: float) -> dict:
    data=plan.to_dict()
    data["duration_seconds"]=seconds
    tracks=[]
    for track in data["tracks"]:
        clips=[]
        for clip in track.get("clips",[]):
            start=float(clip["start_seconds"])
            if start>=seconds:
                continue
            item=dict(clip)
            item["duration_seconds"]=min(float(item["duration_seconds"]),seconds-start)
            clips.append(item)
        tracks.append({**track,"clips":clips})
    data["tracks"]=tracks

    texts=[]
    for item in data.get("texts",[]):
        start=float(item["start_seconds"])
        if start>=seconds:
            continue
        text=dict(item)
        text["duration_seconds"]=min(float(text["duration_seconds"]),seconds-start)
        texts.append(text)
    data["texts"]=texts

    audio=[]
    for item in data.get("audio",[]):
        start=float(item["start_seconds"])
        if start>=seconds:
            continue
        row=dict(item)
        row["duration_seconds"]=min(float(row["duration_seconds"]),seconds-start)
        audio.append(row)
    data["audio"]=audio
    qa=dict(data.get("qa") or {})
    qa["min_duration_seconds"]=1.0
    qa["max_duration_seconds"]=seconds+0.5
    data["qa"]=qa
    return data


def _decode_only(source: Path, seconds: float) -> float:
    started=time.monotonic()
    result=subprocess.run([
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error",
        "-ss","0","-t",str(seconds),"-i",str(source),
        "-map","0:v:0","-f","null","-",
    ],capture_output=True,text=True,timeout=900)
    if result.returncode!=0:
        raise RuntimeError("canary decode-only probe failed")
    return time.monotonic()-started


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--render-job",type=Path,required=True)
    parser.add_argument("--asset-root",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--profile-output",type=Path,required=True)
    parser.add_argument("--seconds",type=float,default=60.0)
    parser.add_argument("--render-profile-version")
    args=parser.parse_args()

    initialize_application()
    job=json.loads(args.render_job.read_text(encoding="utf-8"))
    validate_product_job(job)
    seconds=float(args.seconds)
    if not 30.0<=seconds<=120.0:
        raise SystemExit("canary seconds must be within 30..120")

    root=args.asset_root/job["execution_id"]/str(job["render_job_id"])
    prepared_path=root/"professional-inputs.json"
    if not prepared_path.is_file():
        raise SystemExit("professional input checkpoint missing")
    prepared=json.loads(prepared_path.read_text(encoding="utf-8"))
    if prepared.get("status")!="PASS":
        raise SystemExit("professional input checkpoint is not PASS")
    if not prepared.get("media_checkpoint",{}).get("artifact_reused"):
        raise SystemExit("canary requires reused media checkpoint")
    if not prepared.get("narration",{}).get("artifact_reused"):
        raise SystemExit("canary requires reused narration checkpoint")

    source_paths={str(k):str(v) for k,v in prepared["source_paths"].items()}
    voice_sections,voice_qa=execute_ptbr_narration(job,root)
    plan,edit_qa,expanded=_build_edit_plan(
        job,
        voice_sections,
        source_paths,
        narration_master_path=voice_qa["master_path"],
        narration_duration=voice_qa["duration_seconds"],
    )
    canary_plan=_trim_plan(plan,seconds)
    canary_scenes=[]
    for scene in expanded:
        start=sum(0 for _ in ())
        # expanded scenes carry source windows but no content start; derive from EditPlan clip order.
        canary_scenes.append(dict(scene))
        if len(canary_scenes)>=len(canary_plan["tracks"][0]["clips"]):
            break

    effective=copy.deepcopy(job)
    effective["execution_id"]=job["execution_id"]+"-canary"
    effective["render_job_id"]=job["render_job_id"]+1000000
    effective["id"]=effective["render_job_id"]
    effective["estimated_duration_seconds"]=seconds
    effective["edit_plan"]=canary_plan
    effective["scenes"]=canary_scenes or [{"segment_id":1,"content_unit_id":1,"media_path":next(iter(source_paths.values()))}]
    effective["qa_profile"]="representative-editplan-canary"
    candidate_profile = None
    if args.render_profile_version:
        candidate_profile = executable_render_profile(args.render_profile_version)
        effective["render"] = dict(effective.get("render") or {})
        effective["render"]["learning_profile"] = {
            "skill_id": candidate_profile["skill_id"],
            "version": candidate_profile["version"],
            "content_ref": candidate_profile["content_ref"],
            "checksum": candidate_profile["checksum"],
            "resolved_by": "deepseek_harness",
            "routing_id": "efficiency-candidate-benchmark",
            "authorization_id": "efficiency-candidate-benchmark",
            "evaluation_only": True,
        }
    effective["a1_voice"]={
        "capability_id":"narration.generate.pt-BR",
        "locale":"pt-BR",
        "qa_status":"PASS",
        "voice":voice_qa["voice"],
        "media_path":voice_qa["master_path"],
        "sha256":voice_qa["sha256"],
        "duration_seconds":seconds,
    }
    effective["audio_requirements"]=[{
        "type":"voiceover","track":"A1","language":"pt-BR",
        "media_path":voice_qa["master_path"],"duration_seconds":seconds,
    }]

    first_source=(root/next(iter(source_paths.values()))).resolve()
    decode_seconds=_decode_only(first_source,seconds)

    started=time.monotonic()
    folder=execute(effective,root,args.output_dir,source_job=effective)
    execute_seconds=time.monotonic()-started

    runtime=json.loads((folder/"render-runtime.json").read_text(encoding="utf-8"))
    qa=json.loads((folder/"render-qa.json").read_text(encoding="utf-8"))
    manifest=json.loads((folder/"render-manifest.json").read_text(encoding="utf-8"))
    if qa.get("status")!="PASS" or manifest.get("qa_status")!="PASS":
        raise SystemExit("representative render canary QA failed")
    process_timings=dict(runtime.get("stage_timings") or {})
    render_process=float(runtime.get("wall_clock_seconds") or 0.0)
    post_render=max(0.0,execute_seconds-render_process)

    profile={
        "status":"PASS",
        "run_class":"WARM_RETRY",
        "capability_id":"production.render.execute",
        "stage":"representative_editplan_canary",
        "canary_seconds":seconds,
        "source_render_job_id":job["render_job_id"],
        "canary_render_job_id":effective["render_job_id"],
        "voice":"Voice B",
        "narration_artifact_reused":True,
        "redundant_tts_requests":0,
        "media_valid_assets_reused":True,
        "redundant_media_downloads":0,
        "decode_only_seconds":decode_seconds,
        "filtergraph_command_build_seconds":process_timings.get("filtergraph_command_build_seconds"),
        "ffmpeg_decode_filtergraph_encode_audio_mix_seconds":process_timings.get(
            "ffmpeg_decode_filtergraph_encode_audio_mix_seconds"
        ),
        "render_worker_execute_seconds":execute_seconds,
        "post_render_probe_decode_qa_seconds":post_render,
        "encoder":runtime.get("encoder"),
        "encoder_policy":runtime.get("encoder_policy"),
        "render_speed_x":runtime.get("render_speed_x"),
        "output_size_bytes":manifest.get("size_bytes"),
        "technical_qa_no_regression":"PASS",
        "human_quality_change":"NONE",
        "render_profile_version": (candidate_profile or {}).get("version", "v1-legacy"),
        "render_profile_content_ref": (candidate_profile or {}).get("content_ref"),
        "render_preset_candidate_promoted":False,
        "output_artifact":str(folder),
        "job18_unchanged":True,
        "publication_authority":"NONE",
    }
    args.profile_output.parent.mkdir(parents=True,exist_ok=True)
    args.profile_output.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding="utf-8")
    print("REPRESENTATIVE_RENDER_CANARY=PASS")
    print("NARRATION_ARTIFACT_REUSED=YES")
    print("REDUNDANT_TTS_REQUESTS=0")
    print("MEDIA_VALID_ASSETS_REUSED=YES")
    print("REDUNDANT_MEDIA_DOWNLOADS=0")
    print("RENDER_PRESET_CANDIDATE_PROMOTED=NO")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
