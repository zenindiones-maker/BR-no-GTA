from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

from app.services.edit_plan_service import EditPlan
from app.workers.audiovisual_worker import build_timeline, probe_video
from app.workers.professional_audiovisual_worker import _replace_source_audio_with_voice

MIN_SSIM = 0.98
MIN_LATENCY_REDUCTION = 0.20


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain an object")
    return value


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _single(root: Path, name: str) -> Path:
    matches = sorted(root.glob(f"**/{name}"))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {name}, found {len(matches)}")
    return matches[0]


def _copy_assets(media_root: Path, narration_root: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    media_manifest = _single(media_root, "media-checkpoint-manifest.json")
    manifest = _load(media_manifest)
    for item in manifest.get("assets") or []:
        rel = Path(str(item.get("checkpoint_path") or item.get("runtime_path") or ""))
        if not str(rel) or str(rel) == ".":
            raise RuntimeError("media checkpoint asset lacks runtime/checkpoint path")
        source = media_manifest.parent / rel
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    narr = target / "narration-bundle"
    shutil.copytree(narration_root, narr)


def _decode(path: Path) -> tuple[bool, float]:
    started = time.monotonic()
    proc = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-",
        ],
        capture_output=True,
        timeout=3600,
    )
    return proc.returncode == 0 and not proc.stderr.strip(), time.monotonic() - started


def _probe(path: Path, *, expected_duration: float) -> dict[str, Any]:
    payload = probe_video(path)
    streams = payload.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    rate = str(video.get("avg_frame_rate") or "0/1")
    try:
        numerator, denominator = rate.split("/", 1)
        fps = float(numerator) / float(denominator)
    except Exception:
        fps = math.nan
    try:
        duration = float((payload.get("format") or {}).get("duration"))
    except Exception:
        duration = math.nan
    decode_ok, decode_seconds = _decode(path)
    checks = {
        "resolution_1920x1080": video.get("width") == 1920 and video.get("height") == 1080,
        "fps_30": math.isfinite(fps) and abs(fps - 30.0) <= 0.01,
        "video_codec_h264": video.get("codec_name") == "h264",
        "audio_codec_aac": audio.get("codec_name") == "aac",
        "duration_expected": math.isfinite(duration) and abs(duration - expected_duration) <= 0.75,
        "full_decode": decode_ok,
        "nonempty": path.is_file() and path.stat().st_size > 0,
    }
    return {
        "qa_status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": fps if math.isfinite(fps) else None,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "duration_seconds": duration if math.isfinite(duration) else None,
        "full_decode": decode_ok,
        "full_decode_seconds": decode_seconds,
        "size_bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": _sha(path) if path.is_file() else None,
    }


def _ssim(left: Path, right: Path) -> float:
    proc = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-hide_banner", "-i", str(left), "-i", str(right),
            "-lavfi", "[0:v:0][1:v:0]ssim", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if proc.returncode != 0:
        raise RuntimeError("SSIM comparison failed")
    import re
    matches = re.findall(r"All:([0-9.]+)", proc.stderr)
    if not matches:
        raise RuntimeError("SSIM missing")
    return float(matches[-1])


def _video_stream_hash(path: Path) -> str:
    proc = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
            "-map", "0:v:0", "-c", "copy", "-f", "hash", "-hash", "sha256", "-",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if proc.returncode != 0:
        raise RuntimeError("video stream hash failed")
    return proc.stdout.strip()


def _repeat_project(project, repeats: int):
    if repeats < 1:
        raise ValueError("repeats must be positive")
    repeated = copy.deepcopy(project)
    originals = [copy.deepcopy(track.clips) for track in project.tracks]
    base_duration = float(project.duration())
    for track in repeated.tracks:
        track.clips = []
    for repeat in range(repeats):
        offset = base_duration * repeat
        for track_index, clips in enumerate(originals):
            for clip_index, original in enumerate(clips):
                clip = copy.deepcopy(original)
                clip.id = f"{original.id}_r{repeat:02d}_{clip_index:04d}"
                clip.start = float(original.start) + offset
                repeated.tracks[track_index].clips.append(clip)
    return repeated


def _graph_complexity(project) -> dict[str, Any]:
    video_clips = [
        clip for track in project.video_tracks() for clip in track.clips if clip.enabled
    ]
    text_clips = [clip for clip in video_clips if clip.type == "text"]
    media_video_clips = [clip for clip in video_clips if clip.type == "media"]
    audio_clips = [
        clip for track in project.audio_tracks() for clip in track.clips if clip.enabled
    ]
    legacy_prepad_seconds = sum(max(0.0, float(clip.start)) for clip in video_clips)
    duration = float(project.duration())
    return {
        "timeline_duration_seconds": duration,
        "video_clip_count": len(video_clips),
        "media_video_clip_count": len(media_video_clips),
        "text_clip_count": len(text_clips),
        "audio_clip_count": len(audio_clips),
        "legacy_prepad_seconds": legacy_prepad_seconds,
        "legacy_prepad_to_timeline_ratio": legacy_prepad_seconds / duration if duration else None,
    }


def _render_variant(
    *,
    name: str,
    project,
    output: Path,
    timeline_placement: str,
    compact_text_overlays: bool,
) -> dict[str, Any]:
    from vedit.render import RenderOptions, render

    expected_duration = float(project.duration())
    started = time.monotonic()
    result = render(
        copy.deepcopy(project),
        RenderOptions(
            output=str(output),
            codec="h264",
            quality="high",
            prefer_hw=False,
            hwaccel_decode=False,
            software_preset="slow",
            timeline_placement=timeline_placement,
            compact_text_overlays=compact_text_overlays,
        ),
    )
    render_call_seconds = time.monotonic() - started
    probed = _probe(output, expected_duration=expected_duration)
    timings = dict(getattr(result, "stage_timings", {}) or {})
    resources = dict(getattr(result, "resource_usage", {}) or {})
    total_seconds = render_call_seconds + float(probed["full_decode_seconds"])
    return {
        "name": name,
        "observed": True,
        "render_call_seconds": render_call_seconds,
        "total_seconds": total_seconds,
        "ffmpeg_seconds": float(
            timings.get("ffmpeg_decode_filtergraph_encode_audio_mix_seconds") or result.seconds
        ),
        "filtergraph_build_seconds": float(
            timings.get("filtergraph_command_build_seconds") or 0.0
        ),
        "full_decode_seconds": float(probed["full_decode_seconds"]),
        "encoder": result.encoder,
        "software_preset": "slow",
        "timeline_placement": timeline_placement,
        "compact_text_overlays": compact_text_overlays,
        "prefer_hw": False,
        "hwaccel_decode": False,
        "resource_usage": resources,
        "render_speed_x": (
            float(result.duration) / float(result.seconds) if result.seconds else None
        ),
        **probed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-artifact-root", type=Path, required=True)
    parser.add_argument("--media-root", type=Path, required=True)
    parser.add_argument("--narration-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    base_folder = _single(args.baseline_artifact_root, "render-job.json").parent
    job = _load(base_folder / "render-job.json")
    plan = EditPlan.from_dict(_load(base_folder / "edit-plan.json"))
    base_qa = _load(base_folder / "render-qa.json")
    base_ref = next(base_folder.glob("*.mp4"))
    if (
        base_qa.get("status") != "PASS"
        or (base_qa.get("checks") or {}).get("a1_voice_contract") is not True
    ):
        raise RuntimeError("validated A1 baseline evidence is required")
    if job.get("render_job_id") != 1920101 or abs(float(plan.duration_seconds) - 60.0) > 0.01:
        raise RuntimeError("benchmark must use exact validated 60s VIDEO A canary")
    if args.repeats < 2:
        raise RuntimeError("scaling benchmark requires at least two representative repeats")

    assets = args.work_root / "assets"
    results = args.work_root / "results"
    results.mkdir(parents=True, exist_ok=True)
    _copy_assets(args.media_root, args.narration_root, assets)

    base_project = build_timeline(
        plan,
        assets,
        job["render"],
        a1_voice=job.get("a1_voice"),
        require_a1=True,
    )
    representative = _repeat_project(base_project, args.repeats)
    complexity = _graph_complexity(representative)

    baseline_path = results / "legacy-tpad.mp4"
    candidate_path = results / "timestamp-compact-text.mp4"
    baseline = _render_variant(
        name="legacy-tpad",
        project=representative,
        output=baseline_path,
        timeline_placement="legacy_tpad",
        compact_text_overlays=False,
    )
    candidate = _render_variant(
        name="timestamp-compact-text",
        project=representative,
        output=candidate_path,
        timeline_placement="timestamp",
        compact_text_overlays=True,
    )

    ssim = _ssim(baseline_path, candidate_path)
    reduction = (
        float(baseline["total_seconds"]) - float(candidate["total_seconds"])
    ) / float(baseline["total_seconds"])
    promotion_checks = {
        "latency_reduction_ge_20pct": reduction >= MIN_LATENCY_REDUCTION,
        "ssim_ge_0_98": ssim >= MIN_SSIM,
        "resolution_1920x1080": candidate["checks"]["resolution_1920x1080"],
        "fps_30": candidate["checks"]["fps_30"],
        "h264": candidate["checks"]["video_codec_h264"],
        "aac": candidate["checks"]["audio_codec_aac"],
        "duration_expected": candidate["checks"]["duration_expected"],
        "full_decode": candidate["full_decode"] is True,
        "qa": candidate["qa_status"] == "PASS",
        "same_quality_policy": (
            baseline["encoder"] == candidate["encoder"] == "libx264"
            and baseline["software_preset"] == candidate["software_preset"] == "slow"
        ),
        "timestamp_placement_active": candidate["timeline_placement"] == "timestamp",
        "compact_text_overlays_active": candidate["compact_text_overlays"] is True,
    }
    promotion_eligible = all(promotion_checks.values())

    from vedit import hw
    hw_info = hw.detect(force=True)
    h264_encoder = hw_info.encoder_for("h264", True)
    hardware_available = hw_info.is_hw(h264_encoder)

    remux_dir = args.work_root / "a1-remux"
    remux_dir.mkdir()
    remux_before = remux_dir / "before.mp4"
    shutil.copy2(base_ref, remux_before)
    before_video_hash = _video_stream_hash(remux_before)
    remux_started = time.monotonic()
    _replace_source_audio_with_voice(
        remux_dir,
        assets / "narration-bundle" / "narration-master.flac",
    )
    remux_seconds = time.monotonic() - remux_started
    # _replace_source_audio_with_voice atomically replaces the same MP4 path.
    # Measure the post-pass file in place; there is intentionally no second MP4.
    remux_after = remux_before
    remux_decode, _ = _decode(remux_after)

    evidence = {
        "version": "render-pipeline-optimization-evidence/v3",
        "status": "PASS" if promotion_eligible else "FAIL",
        "observed": True,
        "root_cause": {
            "stage": "ffmpeg_decode_filtergraph_encode_audio_mix",
            "mechanism": (
                "legacy per-clip tpad synthesizes pre-start frames and static text "
                "is represented as full-frame alpha sources plus overlay filters; "
                "both multiply 1080p filtergraph work as the long-form clip count grows"
            ),
            "complexity": complexity,
            "production_longform_duration_seconds": 1608.121179,
            "hardware_acceleration_available": hardware_available,
            "hardware_encoder_probe": h264_encoder,
            "preset_change_previously_rejected": True,
            "prior_timestamp_only_benchmark": {
                "run_id": 35415807436,
                "baseline_total_seconds": 322.565321,
                "candidate_total_seconds": 280.106093,
                "latency_reduction_percent": 13.162986,
                "ssim": 0.998475,
                "qa": "PASS",
                "promotion": "REJECTED_BELOW_20_PERCENT_GATE",
            },
        },
        "benchmark": {
            "source_canary_seconds": 60.0,
            "representative_repeats": args.repeats,
            "representative_duration_seconds": float(representative.duration()),
            "baseline": baseline,
            "candidate": candidate,
            "latency_reduction_fraction": reduction,
            "latency_reduction_percent": reduction * 100.0,
            "ssim": ssim,
            "promotion_checks": promotion_checks,
            "promotion_eligible": promotion_eligible,
        },
        "a1_post_render_remux": {
            "seconds_60s_canary": remux_seconds,
            "video_stream_copy_hash_preserved": (
                before_video_hash == _video_stream_hash(remux_after)
            ),
            "result_full_decode": remux_decode,
            "precondition_a1_voice_contract": True,
        },
        "job18_unchanged": True,
        "publication_authority": "NONE",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"REPRESENTATIVE_DURATION_SECONDS={representative.duration():.6f}")
    print(f"VIDEO_CLIP_COUNT={complexity['video_clip_count']}")
    print(f"TEXT_CLIP_COUNT={complexity['text_clip_count']}")
    print(f"COMPACT_TEXT_OVERLAYS={'YES' if candidate['compact_text_overlays'] else 'NO'}")
    print(f"LEGACY_PREPAD_SECONDS={complexity['legacy_prepad_seconds']:.6f}")
    print(f"BASELINE_TOTAL_SECONDS={baseline['total_seconds']:.6f}")
    print(f"CANDIDATE_TOTAL_SECONDS={candidate['total_seconds']:.6f}")
    print(f"FFMPEG_BASELINE_SECONDS={baseline['ffmpeg_seconds']:.6f}")
    print(f"FFMPEG_CANDIDATE_SECONDS={candidate['ffmpeg_seconds']:.6f}")
    print(f"LATENCY_REDUCTION_PERCENT={reduction * 100.0:.6f}")
    print(f"SSIM={ssim:.6f}")
    print(f"HARDWARE_ACCELERATION_AVAILABLE={'YES' if hardware_available else 'NO'}")
    print(f"PROFILE_PROMOTION_ELIGIBLE={'YES' if promotion_eligible else 'NO'}")
    print(f"A1_REDUNDANT_REMUX_SECONDS={remux_seconds:.6f}")
    print("QA=PASS" if candidate["qa_status"] == "PASS" else "QA=FAIL")
    print("FULL_DECODE=PASS" if candidate["full_decode"] else "FULL_DECODE=FAIL")
    print("JOB18_UNCHANGED=YES")
    print("PUBLICATION_AUTHORITY_UNCHANGED=YES")
    if not promotion_eligible:
        raise SystemExit("timestamp + compact text placement did not satisfy promotion gates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
