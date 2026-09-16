from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from app.services.telegram_brand_asset_materializer import (
    TelegramBrandAssetMaterializationError,
    materialize_telegram_brand_assets,
)
from app.workers.audiovisual_worker import LINEAGE_FIELDS, probe_video, write_json


WATERMARK_SCALE = 0.16
WATERMARK_OPACITY = 0.78
INTRO_AV_SYNC_TOLERANCE_SECONDS = 0.25


class BrandAssetWorkerError(ValueError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BrandAssetWorkerError(f"Expected JSON object: {path.name}")
    return data


def _brand_root(job: dict[str, Any], runtime_root: Path) -> Path:
    return runtime_root / "branding" / str(job["execution_id"]) / str(job["render_job_id"])


def _finite_positive(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise BrandAssetWorkerError(f"{label} is invalid")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BrandAssetWorkerError(f"{label} is invalid") from exc
    if not math.isfinite(number) or number <= 0:
        raise BrandAssetWorkerError(f"{label} is invalid")
    return number


def _stream_duration(stream: dict[str, Any], fallback: float) -> float:
    raw = stream.get("duration")
    if raw not in (None, "N/A"):
        try:
            duration = float(raw)
        except (TypeError, ValueError):
            duration = math.nan
        if math.isfinite(duration) and duration > 0:
            return duration

    duration_ts = stream.get("duration_ts")
    time_base = str(stream.get("time_base") or "")
    if duration_ts not in (None, "N/A") and re.fullmatch(r"[0-9]+/[0-9]+", time_base):
        numerator, denominator = map(int, time_base.split("/"))
        if denominator > 0:
            duration = float(duration_ts) * numerator / denominator
            if math.isfinite(duration) and duration > 0:
                return duration
    return fallback


def prepare(job: dict[str, Any], runtime_root: Path) -> Path:
    folder = _brand_root(job, runtime_root)
    folder.mkdir(parents=True, exist_ok=False)
    state_path = folder / "brand-state.json"
    evidence_path = folder / "brand-assets.json"

    snapshots = job.get("brand_assets") or []
    if not snapshots:
        write_json(state_path, {"assets": []})
        write_json(evidence_path, {"status": "NO_ACTIVE_ASSETS", "assets": []})
        return state_path

    hydrated, evidence = materialize_telegram_brand_assets(job, folder / "input")
    safe_assets: list[dict[str, Any]] = []
    for item, item_evidence in zip(hydrated, evidence, strict=True):
        path = Path(item["media_path"]).resolve()
        probe = probe_video(path)
        streams = probe.get("streams", [])
        video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
        if not video_streams:
            raise BrandAssetWorkerError(f"{item['asset_type']} has no visual stream")

        safe: dict[str, Any] = {
            "asset_id": item["asset_id"],
            "asset_type": item["asset_type"],
            "telegram_file_unique_id": item["telegram_file_unique_id"],
            "media_path": str(path),
            "mime_type": item.get("mime_type"),
            "duration_seconds": item_evidence.get("duration_seconds"),
            "has_video": True,
            "has_audio": bool(audio_streams),
            "sha256": item_evidence["sha256"],
            "size_bytes": item_evidence["size_bytes"],
        }
        if item["asset_type"] == "intro":
            duration = _finite_positive(item_evidence.get("duration_seconds"), "intro duration")
            if not audio_streams:
                raise BrandAssetWorkerError("official intro must contain audio")
            video_duration = _stream_duration(video_streams[0], duration)
            audio_duration = _stream_duration(audio_streams[0], duration)
            av_delta = abs(video_duration - audio_duration)
            if av_delta > INTRO_AV_SYNC_TOLERANCE_SECONDS:
                raise BrandAssetWorkerError("official intro source audio/video duration mismatch")
            safe.update(
                duration_seconds=duration,
                video_duration_seconds=video_duration,
                audio_duration_seconds=audio_duration,
                av_sync_delta_seconds=av_delta,
                av_sync_verified=True,
            )
        safe_assets.append(safe)

    write_json(state_path, {"assets": safe_assets})
    write_json(
        evidence_path,
        {
            "status": "PASS",
            "materialization_boundary": "cloud-only",
            "telegram_bot_token_persisted": False,
            "assets": evidence,
        },
    )
    return state_path


def _render_dimensions(job: dict[str, Any]) -> tuple[int, int, float]:
    render = job.get("render") or {}
    match = re.fullmatch(r"([0-9]+)x([0-9]+)", str(render.get("resolution") or ""))
    if not match:
        raise BrandAssetWorkerError("render.resolution is invalid")
    width, height = map(int, match.groups())
    fps = _finite_positive(render.get("fps"), "render.fps")
    return width, height, fps


def _normalized_video_filter(index: int, label: str, width: int, height: int, fps: float) -> str:
    return (
        f"[{index}:v]setpts=PTS-STARTPTS,"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=bicubic,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"fps={fps},format=yuv420p[{label}]"
    )


def _normalized_audio_filter(index: int, label: str) -> str:
    return (
        f"[{index}:a]asetpts=PTS-STARTPTS,aresample=48000:first_pts=0,"
        f"aformat=sample_rates=48000:channel_layouts=stereo[{label}]"
    )


def _build_ffmpeg_command(
    *,
    base: Path,
    output: Path,
    assets: list[dict[str, Any]],
    width: int,
    height: int,
    fps: float,
    expected_duration: float,
) -> tuple[list[str], dict[str, Any]]:
    content_duration = _finite_positive(expected_duration, "estimated content duration")
    intro = next((item for item in assets if item["asset_type"] == "intro"), None)
    watermark = next((item for item in assets if item["asset_type"] == "watermark"), None)
    intro_duration = 0.0
    if intro is not None:
        intro_duration = _finite_positive(intro.get("duration_seconds"), "intro duration")
        if intro.get("has_video") is not True or intro.get("has_audio") is not True:
            raise BrandAssetWorkerError("official intro must contain video and audio")

    margin_x = max(24, int(width * 0.02))
    margin_y = max(24, int(height * 0.03))
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(base)]
    indexes: dict[str, int] = {}
    next_index = 1
    if intro is not None:
        indexes["intro"] = next_index
        next_index += 1
        args += ["-i", str(intro["media_path"])]
    if watermark is not None:
        indexes["watermark"] = next_index
        args += ["-loop", "1", "-framerate", str(fps), "-i", str(watermark["media_path"])]

    filters = [
        _normalized_video_filter(0, "contentv", width, height, fps),
        _normalized_audio_filter(0, "contenta"),
    ]
    content_video = "contentv"
    if watermark is not None:
        watermark_width = max(64, int(width * WATERMARK_SCALE))
        filters.append(
            f"[{indexes['watermark']}:v]scale={watermark_width}:-2:flags=bicubic,"
            f"format=rgba,colorchannelmixer=aa={WATERMARK_OPACITY}[wm]"
        )
        filters.append(
            f"[{content_video}][wm]overlay=x=W-w-{margin_x}:y=H-h-{margin_y}:"
            "eof_action=pass:repeatlast=1:shortest=1[watermarkedcontent]"
        )
        content_video = "watermarkedcontent"

    final_video = content_video
    final_audio = "contenta"
    if intro is not None:
        filters.extend(
            [
                _normalized_video_filter(indexes["intro"], "introv", width, height, fps),
                _normalized_audio_filter(indexes["intro"], "introa"),
                f"[introv][introa][{content_video}][contenta]concat=n=2:v=1:a=1[joinedv][joineda]",
            ]
        )
        final_video = "joinedv"
        final_audio = "joineda"

    filters.extend([f"[{final_video}]format=yuv420p[vout]", f"[{final_audio}]anull[aout]"])
    args += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(fps),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-movflags",
        "+faststart",
        str(output),
    ]
    branding = {
        "content_duration_semantics": "estimated_duration_is_content_base",
        "content_expected_duration_seconds": content_duration,
        "intro_duration_seconds": intro_duration,
        "final_expected_duration_seconds": content_duration + intro_duration,
        "intro_source_av_sync_delta_seconds": intro.get("av_sync_delta_seconds") if intro else None,
        "watermark_start_seconds": intro_duration if watermark is not None else None,
        "watermark_scale": WATERMARK_SCALE,
        "watermark_margin": {"x": margin_x, "y": margin_y},
        "watermark_opacity": WATERMARK_OPACITY,
        "watermark_position": "BOTTOM_RIGHT",
        "watermark_applied_to": "CONTENT_ONLY" if watermark is not None else None,
        "normalization": "technical-only-no-trim-no-speed-change",
    }
    return args, branding


def _validate_final(path: Path, expected_duration: float) -> tuple[dict[str, Any], dict[str, Any]]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise BrandAssetWorkerError("branded output is missing or empty")
    probe = probe_video(path)
    streams = probe.get("streams", [])
    kinds = {stream.get("codec_type") for stream in streams}
    try:
        duration = float(probe.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = math.nan
    formats = str(probe.get("format", {}).get("format_name") or "").split(",")
    checks = {
        "mp4_container": "mp4" in formats,
        "video_stream": "video" in kinds,
        "audio_stream": "audio" in kinds,
        "finite_positive_duration": math.isfinite(duration) and duration > 0,
        "expected_duration": math.isfinite(duration)
        and abs(duration - expected_duration) <= max(0.5, expected_duration * 0.01),
        "nonempty_file": path.stat().st_size > 0,
        "ffprobe": True,
    }
    if not all(checks.values()):
        raise BrandAssetWorkerError("branded audiovisual QA failed")
    return probe, {"checks": checks, "duration_seconds": duration}


def apply(job: dict[str, Any], runtime_root: Path, output_root: Path) -> Path:
    folder = _brand_root(job, runtime_root)
    state = _load_json(folder / "brand-state.json")
    assets = state.get("assets") or []
    if not isinstance(assets, list):
        raise BrandAssetWorkerError("brand state assets are invalid")

    render_folder = output_root / str(job["execution_id"]) / str(job["render_job_id"])
    output = render_folder / f"{job['video_id']}.mp4"
    if not output.is_file():
        raise BrandAssetWorkerError("base render output was not found")

    evidence = _load_json(folder / "brand-assets.json")
    if not assets:
        write_json(render_folder / "brand-assets.json", evidence)
        return output

    prior_qa = _load_json(render_folder / "render-qa.json")
    if prior_qa.get("status") != "PASS":
        raise BrandAssetWorkerError("base render QA is not PASS")

    base_probe = probe_video(output)
    content_measured_duration = _finite_positive(
        base_probe.get("format", {}).get("duration"),
        "base content duration",
    )
    width, height, fps = _render_dimensions(job)
    content_expected_duration = _finite_positive(
        job.get("estimated_duration_seconds"),
        "estimated content duration",
    )
    temporary = output.with_name(output.stem + ".branded.tmp.mp4")
    command, branding = _build_ffmpeg_command(
        base=output,
        output=temporary,
        assets=assets,
        width=width,
        height=height,
        fps=fps,
        expected_duration=content_expected_duration,
    )
    branding["content_measured_duration_seconds"] = content_measured_duration
    branding["final_measured_target_seconds"] = (
        content_measured_duration + branding["intro_duration_seconds"]
    )
    process = subprocess.run(command, capture_output=True, text=True, timeout=7200)
    if process.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise BrandAssetWorkerError("FFmpeg brand composition failed")

    probe, validation = _validate_final(
        temporary,
        branding["final_measured_target_seconds"],
    )
    decode = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(temporary),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        timeout=3600,
    )
    if decode.returncode or decode.stderr.strip():
        temporary.unlink(missing_ok=True)
        raise BrandAssetWorkerError("Full decode QA failed after brand composition")

    os.replace(temporary, output)
    intro = next((item for item in assets if item["asset_type"] == "intro"), None)
    watermark = next((item for item in assets if item["asset_type"] == "watermark"), None)
    probe["lineage"] = {key: job[key] for key in LINEAGE_FIELDS}
    probe["brand_assets"] = [
        {
            "asset_id": item["asset_id"],
            "asset_type": item["asset_type"],
            "telegram_file_unique_id": item["telegram_file_unique_id"],
            "sha256": item["sha256"],
        }
        for item in assets
    ]
    probe["branding"] = branding
    write_json(render_folder / "video-probe.json", probe)

    intro_present = intro is not None
    watermark_present = watermark is not None
    branding_checks = {
        "full_decode": True,
        "brand_assets_materialized_in_cloud": evidence.get("status") == "PASS",
        "brand_assets_applied": True,
        "intro_present": intro_present,
        "intro_start_zero": intro_present,
        "intro_duration_measured": intro_present and branding["intro_duration_seconds"] > 0,
        "intro_has_video": intro_present and intro.get("has_video") is True,
        "intro_has_audio": intro_present and intro.get("has_audio") is True,
        "intro_complete": intro_present and validation["checks"]["expected_duration"],
        "intro_av_sync": intro_present and intro.get("av_sync_verified") is True,
        "intro_not_trimmed": intro_present and validation["checks"]["expected_duration"],
        "intro_not_stretched": intro_present,
        "watermark_present": watermark_present,
        "watermark_absent_during_intro": intro_present
        and watermark_present
        and branding["watermark_applied_to"] == "CONTENT_ONLY",
        "watermark_start_after_intro": intro_present
        and watermark_present
        and branding["watermark_start_seconds"] >= branding["intro_duration_seconds"],
        "watermark_position_bottom_right": watermark_present
        and branding["watermark_position"] == "BOTTOM_RIGHT",
        "watermark_aspect_ratio_preserved": watermark_present,
        "watermark_safe_margin": watermark_present
        and branding["watermark_margin"]["x"] > 0
        and branding["watermark_margin"]["y"] > 0,
        "watermark_scale_recorded": watermark_present
        and branding["watermark_scale"] > 0,
    }
    qa = {
        "status": "PASS",
        "stage": "brand-complete",
        "checks": {**validation["checks"], **branding_checks},
        "duration_seconds": validation["duration_seconds"],
        "branding": branding,
        "brand_assets": [
            {"asset_id": item["asset_id"], "asset_type": item["asset_type"]}
            for item in assets
        ],
    }
    qa.update({key: job[key] for key in LINEAGE_FIELDS})
    write_json(render_folder / "render-qa.json", qa)

    with output.open("rb") as stream:
        output_digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {key: job[key] for key in LINEAGE_FIELDS}
    manifest.update(
        filename=output.name,
        size_bytes=output.stat().st_size,
        duration_seconds=validation["duration_seconds"],
        qa_status="PASS",
        sha256=output_digest,
        brand_asset_ids=[item["asset_id"] for item in assets],
        brand_asset_types=[item["asset_type"] for item in assets],
        brand_composition="telegram-cloud-ffmpeg-complete-intro-concat",
        content_duration_semantics="estimated_duration_is_content_base",
        branding=branding,
    )
    write_json(render_folder / "render-manifest.json", manifest)
    write_json(render_folder / "brand-assets.json", evidence)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "apply"))
    parser.add_argument("--render-job", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    try:
        job = _load_json(args.render_job)
        if args.mode == "prepare":
            state_path = prepare(job, args.runtime_root)
            print(f"Brand asset cloud preparation PASS: {state_path}")
        else:
            if args.output_dir is None:
                raise BrandAssetWorkerError("--output-dir is required for apply")
            output = apply(job, args.runtime_root, args.output_dir)
            print(f"Brand asset cloud application PASS: {output}")
    except (BrandAssetWorkerError, TelegramBrandAssetMaterializationError, ValueError, OSError) as exc:
        print(f"Brand asset worker FAIL ({type(exc).__name__}): {str(exc)[:500]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
