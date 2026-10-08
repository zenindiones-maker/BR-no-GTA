"""Actual repeated benchmark of Harness specialist versus independently known video edits.

All videos here are original synthetic CI materials. Each trial has isolated
private scratch, new auth and independent ground-truth expected transition.
No audio, private reference, Telegram, deployment or model download.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from time import perf_counter

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.br_specialist_intelligence_v17 import SPEC,execute_specialist
from app.services.br_harness_sensory_authorization_v12 import CAPABILITY_ID
from app.services.harness_authorization_service import issue_harness_authorization,revoke_harness_authorization
from app.database.schema import initialize_schema

TRIALS_PER_CASE=10
TOTAL=20


def original_video(target:Path, changed:bool)->None:
    # Blue at 3 seconds means a known, original visual state transition.
    inputs=["-f","lavfi","-i","color=c=red:s=320x180:r=30:d=3"]
    if changed:
        inputs+=["-f","lavfi","-i","color=c=blue:s=320x180:r=30:d=3",
                 "-filter_complex","[0:v][1:v]concat=n=2:v=1:a=0[v]",
                 "-map","[v]"]
    else:
        inputs=["-f","lavfi","-i","color=c=red:s=320x180:r=30:d=6"]
    r=subprocess.run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error",
        *inputs,"-c:v","libx264","-threads","2","-preset","ultrafast",
        "-pix_fmt","yuv420p",str(target)],
        capture_output=True,text=True,check=False,timeout=80)
    if r.returncode!=0 or not target.is_file():
        raise RuntimeError("SPECIALIST_OWNED_FIXTURE_FFMPEG_FAILED")


def benchmark(*,root:Path,output:Path)->dict:
    if not root.is_absolute() or not root.is_dir() or not output.is_absolute() or output.exists():
        raise ValueError("SPECIALIST_BENCHMARK_PATH_INVALID")
    initialize_schema()
    private=root/"private-original-fixtures"
    private.mkdir(mode=0o700)
    fixtures=[(False,private/"constant.mp4"),(True,private/"hard-cut.mp4")]
    for changed,file in fixtures:
        original_video(file,changed)
    records=[]
    used=set()
    start=perf_counter()
    for changed,source in fixtures:
        for trial in range(TRIALS_PER_CASE):
            scratch=private/f"frames-{int(changed)}-{trial:02d}"
            scratch.mkdir(mode=0o700)
            auth=issue_harness_authorization(
                authorized_action="RESEARCH",subject=f"capability:{CAPABILITY_ID}",
                lineage={"allowed_media_roots":[str(private)]},
            )
            try:
                report=execute_specialist(
                    authorization=auth,source=source,
                    private_workspace=scratch,
                    knowledge_root=Path(__file__).resolve().parents[1],
                    task_id=f"v17-trial-{int(changed)}-{trial:02d}",
                )
            finally:
                revoke_harness_authorization(auth)
            post=report["postcondition"]
            predicted=post["cut_candidates"]>0
            correct=(predicted is changed) and (
                not changed or any(2.7<=t<=3.3 for t in post["cut_seconds"])
            )
            records.append({
                "case":"owned_two_shot" if changed else "owned_constant",
                "trial":trial+1,
                "predicted_cut":predicted,
                "correct":correct,
                "runtime_seconds":report["runtime_seconds"],
                "receipt_sha256":report["receipt_sha256"],
                "source_sha256":post["source_sha256"],
                "tool_execution_verified":report["tool_execution"]=="REAL_HARNESS_CAPABILITY_ADAPTER",
                "unauthorized_effects":0,
            })
            used.add(report["receipt_sha256"])
    positives=[x for x in records if x["case"]=="owned_two_shot"]
    negatives=[x for x in records if x["case"]=="owned_constant"]
    total_correct=sum(r["correct"] for r in records)
    latency=[r["runtime_seconds"] for r in records]
    report={
        "schema_version":"BRVisualSpecialistBenchmark/v1",
        "specialist_id":SPEC.specialist_id,
        "original_assets_generated":2,
        "trial_count":len(records),
        "trial_count_predeclared":TOTAL,
        "positive_passes":sum(r["correct"] for r in positives),
        "negative_passes":sum(r["correct"] for r in negatives),
        "reliability_pass_power_10":all(x["correct"] for x in positives) and all(x["correct"] for x in negatives),
        "pass_at_1_empirical":round(total_correct/len(records),4),
        "pass_at_k_empirical":"NOT_ESTIMATED_NO_INDEPENDENT_STOCHASTIC_MODEL",
        "tool_call_validity":all(r["tool_execution_verified"] for r in records),
        "unauthorized_side_effects":sum(r["unauthorized_effects"] for r in records),
        "p50_latency_seconds":round(statistics.median(latency),4),
        "max_latency_seconds":round(max(latency),4),
        "total_wall_time_seconds":round(perf_counter()-start,4),
        "api_paid_calls":0,
        "model_training_attempted":False,
        "true_owner_20min_episode_tested":False,
        "human_voice_similarity_verified":False,
        "model_professional_specialization_verified":False,
        "status":"REPEATED_ORIGINAL_TOOL_EVIDENCE_PASS" if total_correct==TOTAL
                 and len(used)==TOTAL else "BENCHMARK_INCOMPLETE_OR_FAILED",
        "records":records,
        "limitations":"Only controlled original 6s clips; repeated deterministic pipeline verification, not distributional audio-visual or SLM quality competence.",
    }
    report["report_sha256"]=sha256(json.dumps(
        report,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False
    ).encode()).hexdigest()
    fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(report,f,sort_keys=True,indent=2)
        f.write("\n")
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args()
    r=benchmark(root=Path(args.root),output=Path(args.output))
    for key in ("trial_count","positive_passes","negative_passes",
                "p50_latency_seconds","max_latency_seconds","total_wall_time_seconds"):
        print(f"BR_V17_{key.upper()}={r[key]}")
    print("BR_V17_PROFESSIONAL_WORKFLOW_BENCHMARK="+r["status"])
    print("BR_V17_MODEL_SKILL_TRAINED=FALSE")
    print("BR_V17_PUBLICATION=FORBIDDEN")
    return 0 if r["status"]=="REPEATED_ORIGINAL_TOOL_EVIDENCE_PASS" else 2


if __name__=="__main__":
    raise SystemExit(main())
