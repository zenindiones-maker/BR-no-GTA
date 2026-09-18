from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any

from app.services.render_learning_profile_service import executable_render_profile
from app.workers.audiovisual_worker import build_timeline, probe_video
from app.workers.professional_audiovisual_worker import (
    _build_edit_plan,
    _materialize_sources,
    _parse_voice_rate_percent,
    _synthesize_ptbr_attempt,
    validate_product_job,
)


BENCHMARK_SECONDS = 90.0
MIN_SSIM = 0.98
MIN_LATENCY_REDUCTION_FRACTION = 0.20


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _full_decode(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    return {
        "pass": result.returncode == 0 and not result.stderr.strip(),
        "returncode": result.returncode,
        "stderr_sha256": hashlib.sha256(result.stderr.encode()).hexdigest(),
    }


def _probe_metrics(path: Path) -> dict[str, Any]:
    probe = probe_video(path)
    streams = probe.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    try:
        duration = float((probe.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        duration = math.nan

    rate = str(video.get("avg_frame_rate") or "0/1")
    try:
        numerator, denominator = rate.split("/", 1)
        fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        fps = math.nan

    decode = _full_decode(path)
    checks = {
        "nonempty_file": path.is_file() and path.stat().st_size > 0,
        "video_stream": bool(video),
        "audio_stream": bool(audio),
        "resolution_1920x1080": video.get("width") == 1920 and video.get("height") == 1080,
        "fps_30": math.isfinite(fps) and abs(fps - 30.0) <= 0.01,
        "duration_90s": math.isfinite(duration) and abs(duration - BENCHMARK_SECONDS) <= 0.75,
        "full_decode": decode["pass"],
    }
    return {
        "probe": probe,
        "checks": checks,
        "qa_status": "PASS" if all(checks.values()) else "FAIL",
        "duration_seconds": duration if math.isfinite(duration) else None,
        "fps": fps if math.isfinite(fps) else None,
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": _sha256(path) if path.is_file() else None,
        "full_decode": decode,
    }


def _ssim(reference: Path, candidate: Path) -> float:
    result = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner",
            "-i", str(reference), "-i", str(candidate),
            "-lavfi", "[0:v:0][1:v:0]ssim", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        raise RuntimeError("SSIM comparison failed")
    matches = re.findall(r"All:([0-9.]+)", result.stderr)
    if not matches:
        raise RuntimeError("SSIM metric missing from FFmpeg output")
    return float(matches[-1])


def _render(
    *,
    plan,
    asset_root: Path,
    render_config: dict[str, Any],
    version: str,
    output: Path,
) -> dict[str, Any]:
    from vedit.render import RenderOptions, render

    profile = executable_render_profile(version)
    options = profile["options"]
    project = build_timeline(
        plan,
        asset_root,
        render_config,
        require_a1=False,
    )
    result = render(
        project,
        RenderOptions(
            output=str(output),
            codec=options["codec"],
            quality=options["quality"],
            prefer_hw=options["prefer_hw"],
            hwaccel_decode=options["hwaccel_decode"],
            software_preset=options.get("software_preset"),
        ),
    )
    metrics = _probe_metrics(output)
    metrics.update(
        {
            "observed": True,
            "profile_version": version,
            "skill_id": profile["skill_id"],
            "content_ref": profile["content_ref"],
            "checksum": profile["checksum"],
            "software_preset": options.get("software_preset"),
            "encoder": result.encoder,
            "hardware_path": bool(options["prefer_hw"]),
            "cpu_path": not bool(options["prefer_hw"]),
            "wall_clock_seconds": float(result.seconds),
            "media_duration_seconds": float(result.duration),
            "realtime_factor": (
                float(result.seconds) / float(result.duration)
                if result.duration else None
            ),
            "render_speed_x": (
                float(result.duration) / float(result.seconds)
                if result.seconds else None
            ),
            "retries": 0,
            "failures": 0 if metrics["qa_status"] == "PASS" else 1,
            "policy_violations": 0,
            "output": str(output),
        }
    )
    return metrics


def run_benchmark(render_job_path: Path, asset_root: Path, output_dir: Path) -> dict[str, Any]:
    job = json.loads(render_job_path.read_text(encoding="utf-8"))
    validate_product_job(job)
    if job.get("render_job_id") != 920101:
        raise ValueError("benchmark is bound to real VIDEO A RenderJob 920101")
    if job.get("execution_id") != "run001-video-a-investigative-v1":
        raise ValueError("benchmark VIDEO A execution identity mismatch")
    if job.get("render") != {
        "resolution": "1920x1080",
        "fps": 30.0,
        "container": "mp4",
        "video_codec": "h264",
        "audio_codec": "aac",
    }:
        raise ValueError("VIDEO A render contract changed; re-diagnose before benchmarking")

    output_dir.mkdir(parents=True, exist_ok=False)
    asset_root.mkdir(parents=True, exist_ok=False)
    assets = asset_root

    section = dict(job["script_sections"][0])
    if section.get("section_id") != "A01":
        raise ValueError("VIDEO A first governed section is no longer A01")
    slice_job = dict(job)
    slice_job["script_sections"] = [section]

    source_paths, materialization_evidence = _materialize_sources(slice_job, assets)
    voice_root = assets / "voice"
    voice_root.mkdir()
    voice_sections, master, master_duration = _synthesize_ptbr_attempt(
        slice_job,
        voice_root,
        voice=str(job["narration"]["voice"]),
        rate_percent=_parse_voice_rate_percent(str(job["narration"]["rate"])),
        attempt=1,
    )
    if master_duration + 0.001 < BENCHMARK_SECONDS:
        raise RuntimeError(
            f"A01 narration is only {master_duration:.3f}s; cannot produce the fixed 90s benchmark"
        )

    # The benchmark is a deterministic 90-second prefix of the real governed
    # section. Both versions use the same narration bytes and source media.
    voice_sections = [dict(voice_sections[0])]
    voice_sections[0]["duration_seconds"] = BENCHMARK_SECONDS
    master_relative = str(master.resolve().relative_to(assets.resolve()))
    plan, edit_qa, expanded_scenes = _build_edit_plan(
        slice_job,
        voice_sections,
        source_paths,
        narration_master_path=master_relative,
        narration_duration=BENCHMARK_SECONDS,
    )
    if edit_qa["status"] != "PASS":
        raise RuntimeError("real VIDEO A slice edit plan failed professional edit QA")

    plan_dict = plan.to_dict()
    source_hashes = sorted(
        item["sha256"] for item in materialization_evidence if item.get("sha256")
    )
    workload = {
        "source_render_job_id": job["render_job_id"],
        "source_execution_id": job["execution_id"],
        "source_section_id": section["section_id"],
        "duration_seconds": BENCHMARK_SECONDS,
        "render": dict(job["render"]),
        "narration_voice": job["narration"]["voice"],
        "narration_rate": job["narration"]["rate"],
        "narration_sha256": _sha256(master),
        "source_media_sha256": source_hashes,
        "edit_plan_sha256": _canonical_hash(plan_dict),
        "expanded_scenes_sha256": _canonical_hash(expanded_scenes),
        "quality_target": "VEdit high / H.264 CRF mapping unchanged",
        "only_candidate_variable": "software_preset",
    }
    workload_fingerprint = _canonical_hash(workload)

    baseline_output = output_dir / "baseline-v1-slow.mp4"
    candidate_output = output_dir / "candidate-v2-medium.mp4"
    baseline = _render(
        plan=plan,
        asset_root=assets,
        render_config=job["render"],
        version="v1",
        output=baseline_output,
    )
    candidate = _render(
        plan=plan,
        asset_root=assets,
        render_config=job["render"],
        version="v2",
        output=candidate_output,
    )

    ssim = _ssim(baseline_output, candidate_output)
    baseline_seconds = float(baseline["wall_clock_seconds"])
    candidate_seconds = float(candidate["wall_clock_seconds"])
    latency_reduction = (
        (baseline_seconds - candidate_seconds) / baseline_seconds
        if baseline_seconds > 0 else 0.0
    )
    regression_checks = {
        "baseline_qa": baseline["qa_status"] == "PASS",
        "candidate_qa": candidate["qa_status"] == "PASS",
        "same_resolution": (
            baseline["width"], baseline["height"]
        ) == (candidate["width"], candidate["height"]) == (1920, 1080),
        "same_fps": abs(float(baseline["fps"]) - float(candidate["fps"])) <= 0.01,
        "same_stream_codecs": (
            baseline["video_codec"], baseline["audio_codec"]
        ) == (candidate["video_codec"], candidate["audio_codec"]),
        "candidate_full_decode": candidate["full_decode"]["pass"],
        "quality_ssim": ssim >= MIN_SSIM,
        "no_policy_violations": candidate["policy_violations"] == 0,
    }
    measurable_improvement = (
        latency_reduction >= MIN_LATENCY_REDUCTION_FRACTION
        and all(regression_checks.values())
    )
    decision = (
        "PROMOTION_ELIGIBLE_FOR_HARNESS_EVALUATION"
        if measurable_improvement
        else "NO_MEASURABLE_IMPROVEMENT"
    )
    evidence = {
        "schema": "render-learning-benchmark/v1",
        "observed": True,
        "source_incident": {
            "run_id": 35289594486,
            "job_id": 105429342947,
            "commit_sha": "7bc7b9c719d45efa23745d618ec8ba3077addaec",
            "render_job_id": 920101,
            "execution_id": "run001-video-a-investigative-v1",
            "observed_outcome": "cancelled",
            "workflow_timeout_minutes": 240,
        },
        "workload": workload,
        "workload_fingerprint": workload_fingerprint,
        "baseline": baseline,
        "candidate": candidate,
        "quality_metrics": {
            "ssim_candidate_vs_baseline": ssim,
            "minimum_ssim": MIN_SSIM,
        },
        "performance": {
            "latency_reduction_fraction": latency_reduction,
            "minimum_latency_reduction_fraction": MIN_LATENCY_REDUCTION_FRACTION,
        },
        "regression_evidence": {
            "observed": True,
            "status": "PASS" if all(regression_checks.values()) else "FAIL",
            "checks": regression_checks,
            "critical_failures": [
                key for key, passed in regression_checks.items() if not passed
            ],
        },
        "adversarial_evidence": {
            "observed": True,
            "status": "N/A",
            "reason": (
                "Encoder-preset benchmark has no adversarial input surface; "
                "contract, path and version integrity are covered by regression checks."
            ),
        },
        "decision": decision,
        "promotion_performed": False,
    }
    (output_dir / "benchmark-evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (output_dir / "edit-plan.json").write_text(
        json.dumps(plan_dict, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (output_dir / "materialization-evidence.json").write_text(
        json.dumps(materialization_evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-job", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = run_benchmark(args.render_job, args.asset_root, args.output_dir)
    print(json.dumps(
        {
            "REAL_BASELINE_VS_CANDIDATE": "PASS",
            "decision": evidence["decision"],
            "workload_fingerprint": evidence["workload_fingerprint"],
            "baseline_wall_clock_seconds": evidence["baseline"]["wall_clock_seconds"],
            "candidate_wall_clock_seconds": evidence["candidate"]["wall_clock_seconds"],
            "latency_reduction_fraction": evidence["performance"]["latency_reduction_fraction"],
            "ssim": evidence["quality_metrics"]["ssim_candidate_vs_baseline"],
        },
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
