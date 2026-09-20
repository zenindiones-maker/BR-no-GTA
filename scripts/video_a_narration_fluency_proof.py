from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.services.narration_pipeline import generate_narration_bundle


def _find(root: Path, name: str) -> Path:
    matches=[p for p in root.rglob(name) if p.is_file()]
    if len(matches)!=1:
        raise RuntimeError(f"expected exactly one {name} under {root}, found {len(matches)}")
    return matches[0]


def _run(cmd: list[str]) -> None:
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=600)
    if result.returncode!=0:
        raise RuntimeError(f"command failed: {cmd[0]}: {result.stderr[-1200:]}")


def _baseline_edges(segment: dict[str, Any]) -> tuple[float,float]:
    timing=list(segment.get("timing") or [])
    duration=float(segment.get("audio_duration_seconds") or 0.0)
    if not timing or duration<=0:
        raise RuntimeError(f"baseline native timing missing for {segment.get('segment_id')}")
    first=min(float(x.get("offset_seconds") or 0.0) for x in timing)
    last=max(
        float(x.get("offset_seconds") or 0.0)+float(x.get("duration_seconds") or 0.0)
        for x in timing
    )
    return max(0.0,first),max(0.0,duration-last)


def _joins(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows=[]
    for i in range(len(segments)-1):
        left=_baseline_edges(segments[i]); right=_baseline_edges(segments[i+1])
        rows.append({
            "index":i,
            "left_segment_id":segments[i]["segment_id"],
            "right_segment_id":segments[i+1]["segment_id"],
            "pause_seconds":left[1]+right[0],
            "left_tail_seconds":left[1],
            "right_lead_seconds":right[0],
        })
    return rows


def _window(length: int, center: int) -> tuple[int,int]:
    start=max(0,center-1)
    end=min(length,start+3)
    start=max(0,end-3)
    return start,end


def _extract_baseline(
    *,
    baseline_master: Path,
    speech_timing: dict[str, Any],
    segment_ids: list[str],
    output: Path,
) -> dict[str,float]:
    rows={str(x["segment_id"]):x for x in speech_timing.get("segments") or []}
    selected=[rows[x] for x in segment_ids]
    start=min(float(x["start_seconds"]) for x in selected)
    end=max(float(x["end_seconds"]) for x in selected)
    output.parent.mkdir(parents=True,exist_ok=True)
    _run([
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
        "-ss",f"{start:.6f}","-i",str(baseline_master),
        "-t",f"{end-start:.6f}",
        "-vn","-c:a","libmp3lame","-b:a","128k",str(output),
    ])
    return {"start_seconds":start,"end_seconds":end,"duration_seconds":end-start}


def _encode_candidate(master: Path, output: Path) -> None:
    output.parent.mkdir(parents=True,exist_ok=True)
    _run([
        "ffmpeg","-nostdin","-hide_banner","-loglevel","error","-y",
        "-i",str(master),"-vn","-c:a","libmp3lame","-b:a","128k",str(output),
    ])


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’\-][A-Za-zÀ-ÿ0-9]+)?",text.casefold()))


def _scenario(
    *,
    label: str,
    indexes: tuple[int,int],
    segments: list[dict[str, Any]],
    job: dict[str, Any],
    baseline_master: Path,
    speech_timing: dict[str, Any],
    output: Path,
    cache_root: Path,
) -> dict[str, Any]:
    start,end=indexes
    chosen=segments[start:end]
    section_ids=[str(x["section_id"]) for x in chosen]
    by_id={str(x["section_id"]):x for x in job["script_sections"]}
    sections=[copy.deepcopy(by_id[x]) for x in section_ids]

    baseline_text=" ".join(str(x.get("original_text") or "") for x in chosen)
    candidate_text=" ".join(str(x.get("narration") or "") for x in sections)
    if _normalize(baseline_text)!=_normalize(candidate_text):
        raise RuntimeError(f"{label}: baseline/candidate canonical text differs")

    scenario_root=output/label
    baseline_audio=scenario_root/"baseline-rejected.mp3"
    candidate_audio=scenario_root/"candidate-fluency.mp3"
    baseline_slice=_extract_baseline(
        baseline_master=baseline_master,
        speech_timing=speech_timing,
        segment_ids=[str(x["segment_id"]) for x in chosen],
        output=baseline_audio,
    )

    candidate_job=copy.deepcopy(job)
    candidate_job["script_sections"]=sections
    candidate_job["narration"]["voice"]="pt-BR-ThalitaMultilingualNeural"
    candidate_job["narration"]["language"]="pt-BR"
    candidate_job["narration"]["rate"]="+0%"
    candidate_job["narration"]["rate_locked"]=True
    candidate_job["narration"]["segment_strategy"]="semantic-section-v1"
    bundle=scenario_root/"candidate-bundle"
    _,qa=generate_narration_bundle(
        candidate_job,
        bundle,
        cache_root=cache_root,
        concurrency=min(3,len(sections)),
        lineage={
            "proof":"VIDEO_A_HUMAN_REVIEW_FLUENCY_REMEDIATION",
            "source_render_run_id":35519387625,
            "source_narration_artifact_id":10606237268,
            "scenario":label,
        },
    )
    master=Path(qa["master_path"])
    _encode_candidate(master,candidate_audio)

    baseline_local=_joins(chosen)
    baseline_max=max((float(x["pause_seconds"]) for x in baseline_local),default=0.0)
    fluency=dict(qa.get("fluency") or {})
    candidate_max=float(fluency.get("max_planned_section_boundary_pause_seconds") or 0.0)
    plans=list(qa.get("pronunciation_plans") or [])
    foreign=[
        span
        for plan in plans if isinstance(plan,dict)
        for span in (plan.get("spans") or [])
        if isinstance(span,dict) and str(span.get("locale") or "pt-BR")!="pt-BR"
    ]
    checks={
        "same_canonical_text":True,
        "voice_b_preserved":qa.get("voice")=="pt-BR-ThalitaMultilingualNeural",
        "default_locale_ptbr":qa.get("language")=="pt-BR",
        "only_vice_city_foreign":all(x.get("pronunciation_identity")=="vice-city" for x in foreign),
        "narration_fluency":fluency.get("NARRATION_FLUENCY")=="PASS",
        "no_audible_chunk_boundaries":fluency.get("NO_AUDIBLE_CHUNK_BOUNDARIES")=="PASS",
        "no_unplanned_pauses":fluency.get("NO_UNPLANNED_PAUSES")=="PASS",
        "continuous_ptbr_prosody":fluency.get("CONTINUOUS_PTBR_PROSODY")=="PASS",
    }
    return {
        "label":label,
        "section_ids":section_ids,
        "baseline_segment_ids":[str(x["segment_id"]) for x in chosen],
        "baseline_slice":baseline_slice,
        "baseline_max_boundary_pause_seconds":baseline_max,
        "candidate_max_boundary_pause_seconds":candidate_max,
        "boundary_pause_delta_seconds":baseline_max-candidate_max,
        "baseline_joins":baseline_local,
        "candidate_fluency":fluency,
        "candidate_qa_status":qa.get("status"),
        "candidate_words_per_minute":qa.get("words_per_minute"),
        "candidate_duration_seconds":qa.get("duration_seconds"),
        "foreign_spans":foreign,
        "checks":checks,
        "baseline_audio":str(baseline_audio),
        "candidate_audio":str(candidate_audio),
    }


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--baseline-root",type=Path,required=True)
    ap.add_argument("--render-job-root",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()

    manifest_path=_find(args.baseline_root,"narration-manifest.json")
    timing_path=_find(args.baseline_root,"speech-timing.json")
    master_path=_find(args.baseline_root,"narration-master.flac")
    job_path=_find(args.render_job_root,"render-job.json")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    speech_timing=json.loads(timing_path.read_text(encoding="utf-8"))
    job=json.loads(job_path.read_text(encoding="utf-8"))
    segments=sorted(list(manifest.get("segments") or []),key=lambda x:int(x["order"]))
    if len(segments)<3:
        raise RuntimeError("rejected baseline must contain at least three physical segments")
    if job.get("narration",{}).get("voice")!="pt-BR-ThalitaMultilingualNeural":
        raise RuntimeError("rejected baseline Voice B identity mismatch")

    baseline_joins=_joins(segments)
    worst=max(baseline_joins,key=lambda x:float(x["pause_seconds"]))
    worst_window=_window(len(segments),int(worst["index"]))

    foreign_index=next(
        (
            i for i,x in enumerate(segments)
            if int((x.get("synthesis_plan") or {}).get("foreign_span_count") or 0)>0
        ),
        None,
    )
    if foreign_index is None:
        raise RuntimeError("rejected baseline contains no Vice City mixed-locale stress segment")
    foreign_window=_window(len(segments),foreign_index)

    if args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True)
    cache=args.output_dir/"candidate-cache"
    scenarios=[
        _scenario(
            label="worst-section-boundary",
            indexes=worst_window,
            segments=segments,
            job=job,
            baseline_master=master_path,
            speech_timing=speech_timing,
            output=args.output_dir,
            cache_root=cache,
        ),
        _scenario(
            label="vice-city-locale-boundary",
            indexes=foreign_window,
            segments=segments,
            job=job,
            baseline_master=master_path,
            speech_timing=speech_timing,
            output=args.output_dir,
            cache_root=cache,
        ),
    ]
    worst_result=scenarios[0]
    all_checks=all(all(row["checks"].values()) and row["candidate_qa_status"]=="PASS" for row in scenarios)
    measurable_improvement=(
        float(worst_result["baseline_max_boundary_pause_seconds"])>=0.75
        and float(worst_result["candidate_max_boundary_pause_seconds"])<=0.55
        and float(worst_result["boundary_pause_delta_seconds"])>=0.20
    )
    status="PASS" if all_checks and measurable_improvement else "FAIL"
    result={
        "schema":"video-a-narration-fluency-proof/v1",
        "status":status,
        "source":{
            "human_review_status":"REJECTED",
            "render_run_id":35519387625,
            "narration_artifact_id":10606237268,
            "voice":"pt-BR-ThalitaMultilingualNeural",
            "default_locale":"pt-BR",
        },
        "root_cause":{
            "old_assembly":"mp3-stream-copy-concat",
            "old_physical_segment_count":len(segments),
            "baseline_worst_join":worst,
            "old_qa_gap":"silence QA did not inspect sub-second TTS word-edge joins",
        },
        "candidate":{
            "assembly":"native-word-edge-trim-decoded-pcm-concat",
            "mixed_locale_join":"safe-margin-acrossfade",
            "voice":"pt-BR-ThalitaMultilingualNeural",
            "only_forced_en_us_term":"Vice City",
        },
        "scenarios":scenarios,
        "NARRATION_FLUENCY":"PASS" if status=="PASS" else "FAIL",
        "NO_AUDIBLE_CHUNK_BOUNDARIES":"PASS" if status=="PASS" else "FAIL",
        "NO_UNPLANNED_PAUSES":"PASS" if status=="PASS" else "FAIL",
        "CONTINUOUS_PTBR_PROSODY":"PASS" if status=="PASS" else "FAIL",
        "MEASURABLE_BASELINE_CANDIDATE_IMPROVEMENT":"PASS" if measurable_improvement else "FAIL",
        "HUMAN_AUDIO_REVIEW_STATUS":"PENDING",
    }
    (args.output_dir/"narration-fluency-proof.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8"
    )
    print("NARRATION_FLUENCY="+result["NARRATION_FLUENCY"])
    print("NO_AUDIBLE_CHUNK_BOUNDARIES="+result["NO_AUDIBLE_CHUNK_BOUNDARIES"])
    print("NO_UNPLANNED_PAUSES="+result["NO_UNPLANNED_PAUSES"])
    print("CONTINUOUS_PTBR_PROSODY="+result["CONTINUOUS_PTBR_PROSODY"])
    print(f"BASELINE_WORST_BOUNDARY_PAUSE={worst_result['baseline_max_boundary_pause_seconds']:.6f}")
    print(f"CANDIDATE_WORST_BOUNDARY_PAUSE={worst_result['candidate_max_boundary_pause_seconds']:.6f}")
    print("HUMAN_AUDIO_REVIEW_STATUS=PENDING")
    return 0 if status=="PASS" else 2


if __name__=="__main__":
    raise SystemExit(main())
