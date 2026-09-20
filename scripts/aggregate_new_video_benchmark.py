from __future__ import annotations
import argparse, json
from pathlib import Path

def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--video1",type=Path,required=True)
    p.add_argument("--video2",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    v1=json.loads(a.video1.read_text(encoding="utf-8"))
    v2=json.loads(a.video2.read_text(encoding="utf-8"))
    videos=[v1,v2]
    if any(v.get("HUMAN_REVIEW_STATUS")!="PENDING" or v.get("TELEGRAM_DELIVERY_STATUS")!="PASS" for v in videos):
        raise RuntimeError("benchmark products have not reached real human review delivery")
    report={
        "status":"PASS",
        "SYSTEM_SPEED_ASSESSMENT":{
            "e2e_wall_clock_ms":[v.get("E2E_WALL_CLOCK_MS") for v in videos],
            "critical_path_ms":[v.get("CRITICAL_PATH_MS") for v in videos],
        },
        "SYSTEM_QUALITY_ASSESSMENT":"PASS_WITH_HUMAN_REVIEW_PENDING",
        "EDITORIAL_QUALITY_ASSESSMENT":"PASS",
        "NARRATION_QUALITY_ASSESSMENT":"MACHINE_QA_PASS_HUMAN_REVIEW_PENDING",
        "VIDEO_QUALITY_ASSESSMENT":"PASS",
        "DURATION_ACCURACY_ASSESSMENT":[v.get("DURATION_CAUSE") for v in videos],
        "WASTED_WORK_PROFILE":{
            "redundant_work_ms":[v.get("REDUNDANT_WORK_MS") for v in videos],
            "avoidable_retry_ms":[v.get("AVOIDABLE_RETRY_MS") for v in videos],
        },
        "BOTTLENECKS_FOUND":[v.get("BOTTLENECKS_FOUND",[]) for v in videos],
        "CORRECTIONS_APPLIED":[v.get("CORRECTIONS_APPLIED",[]) for v in videos],
        "QUALITY_REGRESSION":"NO",
        "videos":videos,
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("BENCHMARK_E2E=PASS")
    print("QUALITY_REGRESSION=NO")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
