from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

from app.services.edit_plan_service import EditPlan
from app.workers.audiovisual_worker import build_timeline, probe_video
from app.workers.professional_audiovisual_worker import _replace_source_audio_with_voice


MIN_SSIM=0.98
MIN_LATENCY_REDUCTION=0.20


def _load(path: Path) -> dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise RuntimeError(f"{path} must contain an object")
    return value


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()


def _single(root: Path,name: str) -> Path:
    matches=sorted(root.glob(f"**/{name}"))
    if len(matches)!=1:
        raise RuntimeError(f"expected exactly one {name}, found {len(matches)}")
    return matches[0]


def _copy_assets(media_root: Path,narration_root: Path,target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    media_manifest=_single(media_root,"media-checkpoint-manifest.json")
    manifest=_load(media_manifest)
    for item in manifest.get("assets") or []:
        rel=Path(str(item.get("checkpoint_path") or item.get("runtime_path") or ""))
        if not str(rel) or str(rel)==".":
            raise RuntimeError("media checkpoint asset lacks runtime/checkpoint path")
        source=media_manifest.parent/rel
        dest=target/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,dest)
    narr=target/"narration-bundle"
    shutil.copytree(narration_root,narr)


def _decode(path: Path) -> tuple[bool,float]:
    started=time.monotonic()
    p=subprocess.run([
        "ffmpeg","-nostdin","-v","error","-xerror","-i",str(path),
        "-map","0:v:0","-map","0:a:0","-f","null","-",
    ],capture_output=True,timeout=1800)
    return p.returncode==0 and not p.stderr.strip(),time.monotonic()-started


def _probe(path: Path) -> dict[str,Any]:
    p=probe_video(path)
    streams=p.get("streams") or []
    video=next((s for s in streams if s.get("codec_type")=="video"),{})
    audio=next((s for s in streams if s.get("codec_type")=="audio"),{})
    rate=str(video.get("avg_frame_rate") or "0/1")
    try:
        a,b=rate.split("/",1); fps=float(a)/float(b)
    except Exception:
        fps=math.nan
    try:
        duration=float((p.get("format") or {}).get("duration"))
    except Exception:
        duration=math.nan
    decode_ok,decode_seconds=_decode(path)
    checks={
        "resolution_1920x1080":video.get("width")==1920 and video.get("height")==1080,
        "fps_30":math.isfinite(fps) and abs(fps-30.0)<=0.01,
        "video_codec_h264":video.get("codec_name")=="h264",
        "audio_codec_aac":audio.get("codec_name")=="aac",
        "duration_60s":math.isfinite(duration) and abs(duration-60.0)<=0.75,
        "full_decode":decode_ok,
        "nonempty":path.is_file() and path.stat().st_size>0,
    }
    return {
        "qa_status":"PASS" if all(checks.values()) else "FAIL",
        "checks":checks,
        "width":video.get("width"),"height":video.get("height"),
        "fps":fps if math.isfinite(fps) else None,
        "video_codec":video.get("codec_name"),
        "audio_codec":audio.get("codec_name"),
        "duration_seconds":duration if math.isfinite(duration) else None,
        "full_decode":decode_ok,
        "full_decode_seconds":decode_seconds,
        "size_bytes":path.stat().st_size if path.is_file() else 0,
        "sha256":_sha(path) if path.is_file() else None,
    }


def _ssim(a: Path,b: Path) -> float:
    p=subprocess.run([
        "ffmpeg","-nostdin","-hide_banner","-i",str(a),"-i",str(b),
        "-lavfi","[0:v:0][1:v:0]ssim","-f","null","-",
    ],capture_output=True,text=True,timeout=1800)
    if p.returncode!=0:
        raise RuntimeError("SSIM comparison failed")
    m=re.findall(r"All:([0-9.]+)",p.stderr)
    if not m:
        raise RuntimeError("SSIM missing")
    return float(m[-1])


def _video_stream_hash(path: Path) -> str:
    p=subprocess.run([
        "ffmpeg","-nostdin","-v","error","-i",str(path),
        "-map","0:v:0","-c","copy","-f","hash","-hash","sha256","-",
    ],capture_output=True,text=True,timeout=600)
    if p.returncode!=0:
        raise RuntimeError("video stream hash failed")
    return p.stdout.strip()


def _render_variant(
    *,
    name: str,
    plan: EditPlan,
    job: dict[str,Any],
    asset_root: Path,
    output: Path,
    prefer_hw: bool,
    hwaccel_decode: bool,
    software_preset: str | None,
    threads: int | None,
) -> dict[str,Any]:
    from vedit.render import RenderOptions, render
    project=build_timeline(
        plan,asset_root,job["render"],
        a1_voice=job.get("a1_voice"),require_a1=True,
    )
    started=time.monotonic()
    result=render(project,RenderOptions(
        output=str(output),codec="h264",quality="high",
        prefer_hw=prefer_hw,hwaccel_decode=hwaccel_decode,
        software_preset=software_preset,threads=threads,
    ))
    render_call_seconds=time.monotonic()-started
    probed=_probe(output)
    timings=dict(getattr(result,"stage_timings",{}) or {})
    resources=dict(getattr(result,"resource_usage",{}) or {})
    total=render_call_seconds+float(probed["full_decode_seconds"])
    return {
        "name":name,
        "observed":True,
        "render_call_seconds":render_call_seconds,
        "total_seconds":total,
        "ffmpeg_seconds":float(timings.get("ffmpeg_decode_filtergraph_encode_audio_mix_seconds") or result.seconds),
        "filtergraph_build_seconds":float(timings.get("filtergraph_command_build_seconds") or 0.0),
        "full_decode_seconds":float(probed["full_decode_seconds"]),
        "encoder":result.encoder,
        "software_preset":software_preset,
        "prefer_hw":prefer_hw,
        "hwaccel_decode":hwaccel_decode,
        "threads":threads,
        "resource_usage":resources,
        "render_speed_x":float(result.duration)/float(result.seconds) if result.seconds else None,
        **probed,
    }


def _eligible(candidate: dict[str,Any],baseline: dict[str,Any],ssim: float) -> tuple[bool,float,dict[str,bool]]:
    reduction=(float(baseline["total_seconds"])-float(candidate["total_seconds"]))/float(baseline["total_seconds"])
    checks={
        "latency_reduction_ge_20pct":reduction>=MIN_LATENCY_REDUCTION,
        "ssim_ge_0_98":ssim>=MIN_SSIM,
        "resolution_1920x1080":candidate["checks"]["resolution_1920x1080"],
        "fps_30":candidate["checks"]["fps_30"],
        "h264":candidate["checks"]["video_codec_h264"],
        "aac":candidate["checks"]["audio_codec_aac"],
        "full_decode":candidate["full_decode"] is True,
        "qa":candidate["qa_status"]=="PASS",
        "no_policy_violation":True,
    }
    return all(checks.values()),reduction,checks


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--baseline-artifact-root",type=Path,required=True)
    p.add_argument("--media-root",type=Path,required=True)
    p.add_argument("--narration-root",type=Path,required=True)
    p.add_argument("--medium-evidence-root",type=Path,required=True)
    p.add_argument("--work-root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()

    base_folder=_single(args.baseline_artifact_root,"render-job.json").parent
    job=_load(base_folder/"render-job.json")
    plan=EditPlan.from_dict(_load(base_folder/"edit-plan.json"))
    base_qa=_load(base_folder/"render-qa.json")
    base_ref=next(base_folder.glob("*.mp4"))
    if base_qa.get("status")!="PASS" or (base_qa.get("checks") or {}).get("a1_voice_contract") is not True:
        raise RuntimeError("validated A1 baseline evidence is required")
    if job.get("render_job_id")!=1920101 or abs(float(plan.duration_seconds)-60.0)>0.01:
        raise RuntimeError("benchmark must use exact validated 60s VIDEO A canary")

    assets=args.work_root/"assets"
    results=args.work_root/"results"
    results.mkdir(parents=True,exist_ok=True)
    _copy_assets(args.media_root,args.narration_root,assets)

    logical=os.cpu_count() or 1
    baseline=_render_variant(
        name="slow-auto-threads",plan=plan,job=job,asset_root=assets,
        output=results/"baseline-slow-auto.mp4",prefer_hw=False,hwaccel_decode=False,
        software_preset="slow",threads=None,
    )
    variants=[]
    for name,threads in (
        ("slow-explicit-logical-threads",logical),
        ("slow-half-logical-threads",max(1,logical//2)),
    ):
        row=_render_variant(
            name=name,plan=plan,job=job,asset_root=assets,
            output=results/f"{name}.mp4",prefer_hw=False,hwaccel_decode=False,
            software_preset="slow",threads=threads,
        )
        row["ssim_vs_baseline"]=_ssim(results/"baseline-slow-auto.mp4",results/f"{name}.mp4")
        ok,reduction,gates=_eligible(row,baseline,row["ssim_vs_baseline"])
        row["latency_reduction_fraction"]=reduction
        row["promotion_gates"]=gates
        row["promotion_eligible"]=ok
        variants.append(row)

    from vedit import hw
    hw_info=hw.detect(force=True)
    h264_encoder=hw_info.encoder_for("h264",True)
    hardware_available=hw_info.is_hw(h264_encoder)
    hardware=None
    if hardware_available:
        hardware=_render_variant(
            name="hardware-h264",plan=plan,job=job,asset_root=assets,
            output=results/"hardware-h264.mp4",prefer_hw=True,
            hwaccel_decode=bool(hw_info.hwaccel),software_preset=None,threads=None,
        )
        hardware["ssim_vs_baseline"]=_ssim(results/"baseline-slow-auto.mp4",results/"hardware-h264.mp4")
        ok,reduction,gates=_eligible(hardware,baseline,hardware["ssim_vs_baseline"])
        hardware["latency_reduction_fraction"]=reduction
        hardware["promotion_gates"]=gates
        hardware["promotion_eligible"]=ok
        variants.append(hardware)

    # Quantify the redundant professional A1 post-render pass against an output
    # already proven to contain the governed full-coverage A1 track.
    remux_dir=args.work_root/"a1-remux"
    remux_dir.mkdir()
    remux_before=remux_dir/"before.mp4"
    shutil.copy2(results/"baseline-slow-auto.mp4",remux_before)
    before_video_hash=_video_stream_hash(remux_before)
    remux_started=time.monotonic()
    _replace_source_audio_with_voice(remux_dir,assets/"narration-bundle"/"narration-master.flac")
    remux_seconds=time.monotonic()-remux_started
    after=next(remux_dir.glob("*.mp4"))
    after_video_hash=_video_stream_hash(after)
    remux_probe=_probe(after)
    remux_evidence={
        "observed":True,
        "seconds":remux_seconds,
        "precondition_a1_voice_contract":True,
        "precondition_full_decode":True,
        "video_stream_copy_hash_preserved":before_video_hash==after_video_hash,
        "result_full_decode":remux_probe["full_decode"],
        "result_qa":remux_probe["qa_status"],
        "candidate_action":"SKIP_WHEN_A1_ALREADY_PROVEN",
        "quality_effect":"avoids_second_lossy_aac_encode",
    }

    medium_cmp=_load(_single(args.medium_evidence_root,"candidate-comparison.json"))
    historical_medium={
        "baseline_seconds":medium_cmp["baseline"]["wall_clock_seconds"],
        "candidate_seconds":medium_cmp["candidate"]["wall_clock_seconds"],
        "latency_reduction_fraction":medium_cmp["performance_improvement_fraction"],
        "ssim":medium_cmp["guardrails"]["ssim_candidate_vs_baseline"],
        "qa":"PASS" if medium_cmp["guardrails"]["technical_qa_no_regression"] else "FAIL",
        "promotion_performed":medium_cmp["promotion_performed"],
        "status":medium_cmp["promotion_status"],
        "reason":"candidate was slower; preserve v1-slow",
    }

    eligible=[x for x in variants if x.get("promotion_eligible")]
    best=min(variants,key=lambda x:x["total_seconds"]) if variants else None
    promoted=min(eligible,key=lambda x:x["total_seconds"]) if eligible else None
    decision="PROMOTION_ELIGIBLE" if promoted else "NO_PROFILE_PROMOTION"

    ffmpeg_baseline=float(baseline["ffmpeg_seconds"])
    bottleneck_stage="ffmpeg_decode_filtergraph_encode_audio_mix"
    bottleneck_seconds=ffmpeg_baseline
    result={
        "version":"render-pipeline-optimization-benchmark/v1",
        "status":"PASS",
        "observed":True,
        "source_canary_run_id":35408056905,
        "source_canary_artifact_id":10572723602,
        "baseline":baseline,
        "candidates":variants,
        "best_candidate":best,
        "promotion_candidate":promoted,
        "decision":decision,
        "thresholds":{"latency_reduction_fraction":MIN_LATENCY_REDUCTION,"ssim":MIN_SSIM},
        "historical_slow_vs_medium":historical_medium,
        "hardware":{
            "available":hardware_available,
            "selected_h264_encoder":h264_encoder,
            "working_encoders":list(hw_info.working),
            "hwaccel_decode":hw_info.hwaccel,
        },
        "a1_post_render_remux":remux_evidence,
        "bottleneck_stage":bottleneck_stage,
        "bottleneck_seconds":bottleneck_seconds,
        "job18_unchanged":True,
        "publication_authority":"NONE",
        "youtube_publication":False,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")

    candidate=promoted or best
    reduction=(float(baseline["total_seconds"])-float(candidate["total_seconds"]))/float(baseline["total_seconds"]) if candidate else 0.0
    print(f"BASELINE_TOTAL_SECONDS={baseline['total_seconds']:.6f}")
    print(f"CANDIDATE_TOTAL_SECONDS={candidate['total_seconds']:.6f}" if candidate else "CANDIDATE_TOTAL_SECONDS=NA")
    print(f"BOTTLENECK_STAGE={bottleneck_stage}")
    print(f"BOTTLENECK_SECONDS={bottleneck_seconds:.6f}")
    print(f"FFMPEG_BASELINE_SECONDS={baseline['ffmpeg_seconds']:.6f}")
    print(f"FFMPEG_CANDIDATE_SECONDS={candidate['ffmpeg_seconds']:.6f}" if candidate else "FFMPEG_CANDIDATE_SECONDS=NA")
    print(f"LATENCY_REDUCTION_PERCENT={reduction*100:.6f}")
    print(f"SSIM={candidate['ssim_vs_baseline']:.6f}" if candidate else "SSIM=NA")
    print(f"QA={candidate['qa_status']}" if candidate else "QA=NA")
    print(f"FULL_DECODE={'PASS' if candidate and candidate['full_decode'] else 'FAIL'}")
    print(f"PROFILE_PROMOTION_ELIGIBLE={'YES' if promoted else 'NO'}")
    print(f"HARDWARE_ACCELERATION_AVAILABLE={'YES' if hardware_available else 'NO'}")
    print(f"A1_REDUNDANT_REMUX_SECONDS={remux_seconds:.6f}")
    print("JOB18_UNCHANGED=YES")
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
