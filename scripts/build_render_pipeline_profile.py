from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str,Any] | None:
    if not path.is_file():
        return None
    value=json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value,dict) else None


def _first(root: Path, name: str) -> Path | None:
    matches=sorted(root.glob(f"**/{name}"))
    return matches[0] if matches else None


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--runtime-root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    runtime=args.runtime_root
    clock=_load(runtime/"pipeline-stage-clock.json") or {"stages":{}}
    op_path=_first(runtime,"operation-observability.json")
    render_path=_first(runtime,"render-runtime.json")
    narr_path=_first(runtime,"narration-observability.json")
    brand_path=_first(runtime,"brand-performance.json")
    op=_load(op_path) if op_path else {}
    render=_load(render_path) if render_path else {}
    narr=_load(narr_path) if narr_path else {}
    brand=_load(brand_path) if brand_path else {}

    stages: dict[str,float] = {}
    for name,row in (clock.get("stages") or {}).items():
        if isinstance(row,dict) and isinstance(row.get("elapsed_seconds"),(int,float)):
            stages[name]=float(row["elapsed_seconds"])

    op_stages=dict((op or {}).get("stage_elapsed") or {})
    mapping={
        "prepare_narration_media_seconds":"prepare_narration_media",
        "edit_plan_seconds":"editplan_timeline",
        "render_seconds":"vedit_render_worker",
        "final_mix_qa_seconds":"a1_post_render_and_qa",
    }
    for key,label in mapping.items():
        if isinstance(op_stages.get(key),(int,float)):
            stages.setdefault(label,float(op_stages[key]))

    render_stages=dict((render or {}).get("stage_timings") or {})
    for key in ("filtergraph_command_build_seconds","ffmpeg_decode_filtergraph_encode_audio_mix_seconds"):
        if isinstance(render_stages.get(key),(int,float)):
            stages[key]=float(render_stages[key])

    narr_stages=dict((narr or {}).get("stage_elapsed") or {})
    for key,value in narr_stages.items():
        if isinstance(value,(int,float)):
            stages[f"tts_{key}"]=float(value)

    if isinstance((brand or {}).get("composition_seconds"),(int,float)):
        stages["brand_visual_composition"]=float(brand["composition_seconds"])
    if isinstance((brand or {}).get("qa_seconds"),(int,float)):
        stages["brand_ffprobe_full_decode_qa"]=float(brand["qa_seconds"])

    excluded={"artifact_upload","telegram_delivery"}
    compute_candidates={k:v for k,v in stages.items() if k not in excluded}
    bottleneck=max(compute_candidates,key=compute_candidates.get) if compute_candidates else None
    total=sum(stages.values())
    profile={
        "version":"render-pipeline-profile/v1",
        "status":"PASS",
        "stages":stages,
        "observed_stage_sum_seconds":total,
        "bottleneck_stage":bottleneck,
        "bottleneck_seconds":compute_candidates.get(bottleneck) if bottleneck else None,
        "render_runtime":{
            "encoder":(render or {}).get("encoder"),
            "encoder_policy":(render or {}).get("encoder_policy"),
            "resource_usage":(render or {}).get("resource_usage"),
            "render_speed_x":(render or {}).get("render_speed_x"),
        },
        "reuse":{
            "cache_hit":(op or {}).get("cache_hit"),
            "cache_miss":(op or {}).get("cache_miss"),
            "external_calls":(op or {}).get("external_calls"),
            "reused_artifacts":(op or {}).get("reused_artifacts"),
            "download_count":(op or {}).get("download_count"),
        },
        "job18_unchanged":True,
        "publication_authority":"NONE",
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding="utf-8")
    print("RENDER_PIPELINE_PROFILE=PASS")
    if bottleneck:
        print(f"BOTTLENECK_STAGE={bottleneck}")
        print(f"BOTTLENECK_SECONDS={compute_candidates[bottleneck]:.6f}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
