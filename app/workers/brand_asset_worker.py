from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess

from app.services.telegram_brand_asset_materializer import (
    TelegramBrandAssetMaterializationError,
    materialize_telegram_brand_assets,
)
from app.workers.audiovisual_worker import LINEAGE_FIELDS, probe_video, write_json


class BrandAssetWorkerError(ValueError):
    pass


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BrandAssetWorkerError(f"Expected JSON object: {path.name}")
    return data


def _brand_root(job: dict, runtime_root: Path) -> Path:
    return runtime_root / "branding" / str(job["execution_id"]) / str(job["render_job_id"])


def prepare(job: dict, runtime_root: Path) -> Path:
    folder = _brand_root(job, runtime_root)
    folder.mkdir(parents=True, exist_ok=False)
    state_path = folder / "brand-state.json"
    evidence_path = folder / "brand-assets.json"

    snapshots = job.get("brand_assets") or []
    if not snapshots:
        write_json(state_path, {"assets": []})
        write_json(evidence_path, {"status": "NO_ACTIVE_ASSETS", "assets": []})
        return state_path

    input_root = folder / "input"
    hydrated, evidence = materialize_telegram_brand_assets(job, input_root)
    safe_assets = []
    for item, item_evidence in zip(hydrated, evidence, strict=True):
        path = Path(item["media_path"]).resolve()
        probe = probe_video(path)
        streams = probe.get("streams", [])
        safe_assets.append(
            {
                "asset_id": item["asset_id"],
                "asset_type": item["asset_type"],
                "telegram_file_unique_id": item["telegram_file_unique_id"],
                "media_path": str(path),
                "mime_type": item.get("mime_type"),
                "duration_seconds": item_evidence.get("duration_seconds"),
                "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
                "sha256": item_evidence["sha256"],
                "size_bytes": item_evidence["size_bytes"],
            }
        )

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


def _render_dimensions(job: dict) -> tuple[int, int, float]:
    render = job.get("render") or {}
    match = re.fullmatch(r"([0-9]+)x([0-9]+)", str(render.get("resolution") or ""))
    if not match:
        raise BrandAssetWorkerError("render.resolution is invalid")
    width, height = map(int, match.groups())
    fps = render.get("fps")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(float(fps)) or float(fps) <= 0:
        raise BrandAssetWorkerError("render.fps is invalid")
    return width, height, float(fps)


def _build_ffmpeg_command(
    *,
    base: Path,
    output: Path,
    assets: list[dict],
    width: int,
    height: int,
    fps: float,
    expected_duration: float,
) -> list[str]:
    intro = next((item for item in assets if item["asset_type"] == "intro"), None)
    watermark = next((item for item in assets if item["asset_type"] == "watermark"), None)

    args = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", str(base)]
    indexes: dict[str, int] = {}
    next_index = 1
    if intro is not None:
        indexes["intro"] = next_index
        next_index += 1
        args += ["-i", str(intro["media_path"])]
    if watermark is not None:
        indexes["watermark"] = next_index
        next_index += 1
        args += ["-loop", "1", "-framerate", str(fps), "-i", str(watermark["media_path"])]

    filters: list[str] = ["[0:v]setpts=PTS-STARTPTS[basev]"]
    current_video = "basev"
    current_audio = "0:a"

    if intro is not None:
        intro_duration = float(intro.get("duration_seconds") or 0.0)
        if not math.isfinite(intro_duration) or intro_duration <= 0:
            raise BrandAssetWorkerError("intro duration is invalid")
        intro_duration = min(intro_duration, expected_duration)
        idx = indexes["intro"]
        filters.append(
            f"[{idx}:v]setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={width}:{height}[introv]"
        )
        filters.append(
            f"[{current_video}][introv]overlay=0:0:eof_action=pass:repeatlast=0:"
            f"enable='between(t,0,{intro_duration:.6f})'[withintro]"
        )
        current_video = "withintro"
        if intro.get("has_audio"):
            filters.append(
                f"[0:a]volume=volume=0:enable='between(t,0,{intro_duration:.6f})'[basequiet]"
            )
            filters.append(
                f"[{idx}:a]atrim=0:{intro_duration:.6f},asetpts=PTS-STARTPTS[introa]"
            )
            filters.append(
                "[basequiet][introa]amix=inputs=2:duration=first:normalize=0[brandaudio]"
            )
            current_audio = "brandaudio"

    if watermark is not None:
        idx = indexes["watermark"]
        filters.append(
            f"[{idx}:v]scale='min(iw,{max(64, int(width * 0.16))})':-2:flags=bicubic,"
            "format=rgba,colorchannelmixer=aa=0.78[wm]"
        )
        filters.append(
            f"[{current_video}][wm]overlay=x=W-w-{max(24, int(width * 0.02))}:"
            f"y=H-h-{max(24, int(height * 0.03))}:eof_action=pass:repeatlast=1[brandedv]"
        )
        current_video = "brandedv"

    filters.append(f"[{current_video}]format=yuv420p[vout]")
    if current_audio == "0:a":
        filters.append("[0:a]asetpts=PTS-STARTPTS[aout]")
    else:
        filters.append(f"[{current_audio}]atrim=0:{expected_duration:.6f},asetpts=PTS-STARTPTS[aout]")

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
        "-t",
        f"{expected_duration:.6f}",
        "-movflags",
        "+faststart",
        str(output),
    ]
    return args


def _validate_final(path: Path, expected_duration: float) -> tuple[dict, dict]:
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
    }
    if not all(checks.values()):
        raise BrandAssetWorkerError("branded audiovisual QA failed")
    return probe, {"checks": checks, "duration_seconds": duration}


def apply(job: dict, runtime_root: Path, output_root: Path) -> Path:
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

    width, height, fps = _render_dimensions(job)
    expected = float(job["estimated_duration_seconds"])
    temporary = output.with_name(output.stem + ".branded.tmp.mp4")
    command = _build_ffmpeg_command(
        base=output,
        output=temporary,
        assets=assets,
        width=width,
        height=height,
        fps=fps,
        expected_duration=expected,
    )
    process = subprocess.run(command, capture_output=True, text=True, timeout=7200)
    if process.returncode != 0:
        temporary.unlink(missing_ok=True)
        raise BrandAssetWorkerError("FFmpeg brand composition failed")

    probe, validation = _validate_final(temporary, expected)
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
    write_json(render_folder / "video-probe.json", probe)

    qa = {
        "status": "PASS",
        "stage": "brand-complete",
        "checks": {
            **validation["checks"],
            "full_decode": True,
            "brand_assets_materialized_in_cloud": True,
            "brand_assets_applied": True,
        },
        "duration_seconds": validation["duration_seconds"],
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
        brand_composition="telegram-cloud-ffmpeg",
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
