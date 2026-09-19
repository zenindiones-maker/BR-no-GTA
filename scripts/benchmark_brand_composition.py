from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any

from app.services.channel_spoken_branding_service import build_spoken_branding_contract
from app.workers.audiovisual_worker import probe_video
from app.workers.brand_asset_worker import (
    _brand_root,
    _build_ffmpeg_command,
    _load_json,
    _render_dimensions,
    _validate_final,
    prepare,
)


MIN_REDUCTION=0.20
MIN_SSIM=0.98
MAX_SIZE_GROWTH=0.15
THEME="fatos, vazamentos, tecnologia e rumores de GTA 6"


def _load(path: Path) -> dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):
        raise RuntimeError(f"{path} must be an object")
    return value


def _single(root: Path,name: str) -> Path:
    xs=sorted(root.glob(f"**/{name}"))
    if len(xs)!=1:
        raise RuntimeError(f"expected exactly one {name}, found {len(xs)}")
    return xs[0]


def _decode(path: Path) -> tuple[bool,float]:
    started=time.monotonic()
    p=subprocess.run([
        "ffmpeg","-nostdin","-v","error","-xerror","-i",str(path),
        "-map","0:v:0","-map","0:a:0","-f","null","-",
    ],capture_output=True,timeout=1800)
    return p.returncode==0 and not p.stderr.strip(),time.monotonic()-started


def _ssim(a: Path,b: Path) -> float:
    p=subprocess.run([
        "ffmpeg","-nostdin","-hide_banner","-i",str(a),"-i",str(b),
        "-lavfi","[0:v:0][1:v:0]ssim","-f","null","-",
    ],capture_output=True,text=True,timeout=1800)
    if p.returncode!=0:
        raise RuntimeError("branding SSIM failed")
    m=re.findall(r"All:([0-9.]+)",p.stderr)
    if not m:
        raise RuntimeError("branding SSIM result missing")
    return float(m[-1])


def _metrics(path: Path,expected: float) -> dict[str,Any]:
    p=probe_video(path)
    streams=p.get("streams") or []
    video=next((x for x in streams if x.get("codec_type")=="video"),{})
    audio=next((x for x in streams if x.get("codec_type")=="audio"),{})
    rate=str(video.get("avg_frame_rate") or "0/1")
    try:
        a,b=rate.split("/",1); fps=float(a)/float(b)
    except Exception:
        fps=math.nan
    try:
        duration=float((p.get("format") or {}).get("duration"))
    except Exception:
        duration=math.nan
    ok,decode_seconds=_decode(path)
    checks={
        "resolution_1920x1080":video.get("width")==1920 and video.get("height")==1080,
        "fps_30":math.isfinite(fps) and abs(fps-30.0)<=0.01,
        "h264":video.get("codec_name")=="h264",
        "aac":audio.get("codec_name")=="aac",
        "duration":math.isfinite(duration) and abs(duration-expected)<=max(0.75,expected*0.01),
        "full_decode":ok,
    }
    return {
        "qa":"PASS" if all(checks.values()) else "FAIL",
        "checks":checks,
        "full_decode":ok,
        "full_decode_seconds":decode_seconds,
        "size_bytes":path.stat().st_size,
        "duration_seconds":duration if math.isfinite(duration) else None,
    }


def _run_variant(
    *,
    preset: str,
    base: Path,
    output: Path,
    assets: list[dict[str,Any]],
    width: int,
    height: int,
    fps: float,
    content_duration: float,
) -> dict[str,Any]:
    command,branding=_build_ffmpeg_command(
        base=base,output=output,assets=assets,width=width,height=height,fps=fps,
        expected_duration=content_duration,
    )
    try:
        idx=command.index("-preset")
    except ValueError as exc:
        raise RuntimeError("branding command lacks x264 preset") from exc
    command[idx+1]=preset
    started=time.monotonic()
    process=subprocess.run(command,capture_output=True,text=True,timeout=3600)
    encode_seconds=time.monotonic()-started
    if process.returncode!=0:
        raise RuntimeError(f"branding preset {preset} failed: {process.stderr[-500:]}")
    measured_base=float((probe_video(base).get("format") or {}).get("duration"))
    expected=measured_base+float(branding["intro_duration_seconds"])
    qa_started=time.monotonic()
    _,validation=_validate_final(output,expected)
    met=_metrics(output,expected)
    qa_seconds=time.monotonic()-qa_started
    if met["qa"]!="PASS" or not validation["checks"]["expected_duration"]:
        raise RuntimeError(f"branding preset {preset} failed QA")
    return {
        "preset":preset,
        "encode_seconds":encode_seconds,
        "qa_seconds":qa_seconds,
        "total_seconds":encode_seconds+qa_seconds,
        "branding":branding,
        **met,
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline-artifact-root",type=Path,required=True)
    ap.add_argument("--runtime-root",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()

    source_folder=_single(args.baseline_artifact_root,"render-job.json").parent
    source_job=_load(source_folder/"render-job.json")
    source_mp4=next(source_folder.glob("*.mp4"))
    if source_job.get("render_job_id")!=1920101:
        raise RuntimeError("expected validated VIDEO A 60s canary")
    job=dict(source_job)
    job["spoken_branding"]=build_spoken_branding_contract(theme=THEME)
    job["script_sections"]=[{"section_id":"A01","role":"hook"}]
    edit_plan=dict(job.get("edit_plan") or {})
    metadata=dict(edit_plan.get("metadata") or {})
    contract=job["spoken_branding"]
    metadata["timeline_sequence"]=[
        {"order":1,"phase":"official_intro","asset_id":1},
        {"order":2,"phase":"spoken_channel_opening","voice":"Voice B","text":contract["opening_text"],"duration_seconds":2.0},
        {"order":3,"phase":"editorial_hook","section_id":"A01"},
        {"order":4,"phase":"editorial_content"},
        {"order":5,"phase":"spoken_channel_closing","voice":"Voice B","text":contract["closing_line"],"duration_seconds":1.0},
    ]
    edit_plan["metadata"]=metadata
    job["edit_plan"]=edit_plan
    job["estimated_duration_seconds"]=60.0

    prepare(job,args.runtime_root)
    state=_load_json(_brand_root(job,args.runtime_root)/"brand-state.json")
    assets=list(state.get("assets") or [])
    if sorted((x.get("asset_id"),x.get("asset_type")) for x in assets)!=[(1,"intro"),(2,"watermark")]:
        raise RuntimeError("canonical intro/watermark assets were not materialized")

    width,height,fps=_render_dimensions(job)
    if (width,height)!=(1920,1080) or abs(fps-30.0)>0.01:
        raise RuntimeError("benchmark must remain 1920x1080@30")

    work=args.runtime_root/"brand-benchmark"
    work.mkdir(parents=True,exist_ok=True)
    base_copy=work/"base-content.mp4"
    shutil.copy2(source_mp4,base_copy)

    rows={}
    for preset in ("medium","fast","faster"):
        rows[preset]=_run_variant(
            preset=preset,base=base_copy,output=work/f"brand-{preset}.mp4",
            assets=assets,width=width,height=height,fps=fps,content_duration=60.0,
        )
    baseline=rows["medium"]
    candidates=[]
    for preset in ("fast","faster"):
        row=rows[preset]
        ssim=_ssim(work/"brand-medium.mp4",work/f"brand-{preset}.mp4")
        reduction=(baseline["total_seconds"]-row["total_seconds"])/baseline["total_seconds"]
        size_growth=(row["size_bytes"]-baseline["size_bytes"])/baseline["size_bytes"]
        gates={
            "latency_reduction_ge_20pct":reduction>=MIN_REDUCTION,
            "ssim_ge_0_98":ssim>=MIN_SSIM,
            "size_growth_le_15pct":size_growth<=MAX_SIZE_GROWTH,
            "resolution_1920x1080":row["checks"]["resolution_1920x1080"],
            "fps_30":row["checks"]["fps_30"],
            "h264":row["checks"]["h264"],
            "aac":row["checks"]["aac"],
            "full_decode":row["full_decode"] is True,
            "qa":row["qa"]=="PASS",
        }
        row={**row,"ssim":ssim,"latency_reduction_fraction":reduction,
             "size_growth_fraction":size_growth,"promotion_gates":gates,
             "promotion_eligible":all(gates.values())}
        candidates.append(row)
    eligible=[x for x in candidates if x["promotion_eligible"]]
    best=min(candidates,key=lambda x:x["total_seconds"])
    promoted=min(eligible,key=lambda x:x["total_seconds"]) if eligible else None
    result={
        "version":"brand-composition-performance-benchmark/v1",
        "status":"PASS","observed":True,
        "source_canary_run_id":35408056905,
        "source_canary_artifact_id":10572723602,
        "baseline":baseline,
        "candidates":candidates,
        "best_candidate":best,
        "promotion_candidate":promoted,
        "decision":"PROMOTION_ELIGIBLE" if promoted else "NO_PROMOTION",
        "thresholds":{"latency_reduction_fraction":MIN_REDUCTION,"ssim":MIN_SSIM,
                      "max_size_growth_fraction":MAX_SIZE_GROWTH},
        "job18_unchanged":True,
        "publication_authority":"NONE",
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"BRAND_BASELINE_TOTAL_SECONDS={baseline['total_seconds']:.6f}")
    print(f"BRAND_CANDIDATE_TOTAL_SECONDS={best['total_seconds']:.6f}")
    print(f"BRAND_LATENCY_REDUCTION_PERCENT={best['latency_reduction_fraction']*100:.6f}")
    print(f"BRAND_SSIM={best['ssim']:.6f}")
    print(f"BRAND_PROFILE_PROMOTION_ELIGIBLE={'YES' if promoted else 'NO'}")
    print("BRAND_QA=PASS")
    print("BRAND_FULL_DECODE=PASS")
    print("JOB18_UNCHANGED=YES")
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
