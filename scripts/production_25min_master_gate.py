#!/usr/bin/env python3
"""RUN-001 owner-targeted 25-minute master verification before YouTube PRIVATE.

A short demo, audio-free render, missing proof, or 20-minute padding cannot pass.
This is additive to (not a replacement for) editorial, voice, semantic and
no-artificial-padding gates. It neither dispatches nor publishes anything.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

TARGET_MIN_SEC = 24 * 60
TARGET_MAX_SEC = 26 * 60
OUTPUT_SCHEMA = "BRRun001PrivateMaster25Minutes/v1"


class MasterGateError(ValueError):
    pass


def check_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    streams = metadata.get("streams", [])
    if not isinstance(streams, list):
        raise MasterGateError("FFPROBE_STREAMS_MISSING")
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    others = [s for s in streams if s.get("codec_type") not in ("video", "audio")]
    if len(videos) != 1 or len(audios) != 1 or others:
        raise MasterGateError("REQUIRE_ONE_VIDEO_ONE_AUDIO_NO_SUBTITLES")
    video, audio = videos[0], audios[0]
    if (video.get("codec_name"), video.get("profile"), video.get("pix_fmt")) != ("h264", "High", "yuv420p"):
        raise MasterGateError("H264_HIGH_YUV420P_REQUIRED")
    if (video.get("width"), video.get("height")) != (1920, 1080):
        raise MasterGateError("FULL_HD_REQUIRED")
    try:
        fps = Fraction(str(video.get("avg_frame_rate") or video.get("r_frame_rate")))
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise MasterGateError("VIDEO_FRAME_RATE_INVALID") from exc
    if not Fraction(2997, 100) <= fps <= Fraction(30, 1):
        raise MasterGateError("VIDEO_FPS_30_REQUIRED")
    if (audio.get("codec_name"), audio.get("sample_rate"), audio.get("channels")) != ("aac", "48000", 2):
        raise MasterGateError("AAC_48KHZ_STEREO_REQUIRED")
    try:
        duration = float(metadata["format"]["duration"])
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise MasterGateError("REAL_DURATION_MISSING") from exc
    import math
    if not math.isfinite(duration) or not TARGET_MIN_SEC <= duration <= TARGET_MAX_SEC:
        raise MasterGateError("OWNER_25MIN_DURATION_REQUIRED")
    try:
        declared_frames = int(video["nb_frames"])
    except (KeyError, ValueError, TypeError) as exc:
        raise MasterGateError("VIDEO_FRAME_COUNT_MISSING") from exc
    # MP4 container header can be inconsistent; the full decode is an
    # independent prerequisite of the existing canonical render QA.
    if abs(declared_frames - round(duration * float(fps))) > max(30, round(float(fps))):
        raise MasterGateError("FRAME_COUNT_DURATION_INCONSISTENT")
    return {
        "duration_seconds": duration,
        "duration_minutes": round(duration / 60, 3),
        "video_frames_declared": declared_frames,
        "video_fps": str(fps),
        "video_codec": "h264", "video_profile": "High",
        "pixel_format": "yuv420p", "width": 1920, "height": 1080,
        "audio_codec": "aac", "audio_channels": 2, "audio_sample_rate": 48000,
    }


def probe_real_master(master: Path) -> dict[str, Any]:
    if master.is_symlink() or not master.is_file() or master.suffix.lower() != ".mp4":
        raise MasterGateError("MASTER_MUST_BE_REAL_MP4")
    if not 1_000_000 < master.stat().st_size < 25_000_000_000:
        raise MasterGateError("MASTER_FILE_SIZE_NOT_PROFESSIONAL")
    proc = subprocess.run([
        "ffprobe", "-hide_banner", "-v", "error",
        "-show_entries", "format=duration:stream=codec_type,codec_name,profile,pix_fmt,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels,nb_frames",
        "-of", "json", str(master),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, timeout=55)
    if proc.returncode != 0 or len(proc.stdout) > 200_000:
        raise MasterGateError("REAL_FFPROBE_FAILED")
    try:
        return json.loads(proc.stdout)
    except (ValueError, UnicodeDecodeError) as exc:
        raise MasterGateError("FFPROBE_JSON_INVALID") from exc


def inspect(master: Path, case: str) -> dict[str, Any]:
    if case not in {"A", "B"}:
        raise MasterGateError("RUN001_CASE_MUST_BE_A_OR_B")
    metadata = probe_real_master(master)
    info = check_metadata(metadata)
    # Content assessment, approved BR_OWNER_V1 voice and legitimate editorial
    # runtime are separately required. No surrogate confidence assertion.
    digest = hashlib.sha256()
    with master.open("rb") as fd:
        for block in iter(lambda: fd.read(1 << 20), b""):
            digest.update(block)
    return {
        "schema": OUTPUT_SCHEMA, "case": case, "media_sha256": digest.hexdigest(),
        "status": "PASS", "media": info,
        "only_run001_duration_codec_gate": True,
        "owner_voice_human_approval": "NOT_ASSESSED_HERE",
        "editorial_no_padding": "NOT_ASSESSED_HERE",
        "youtube_private_hd": "NOT_UPLOADED",
        "production_release_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--case", choices=["A", "B"], required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    a = parser.parse_args()
    result: dict[str, Any]
    try:
        result = inspect(a.master, a.case)
    except (MasterGateError, OSError, subprocess.TimeoutExpired) as exc:
        result = {"schema": OUTPUT_SCHEMA, "case": a.case, "status": "FAIL",
                  "failure_class": type(exc).__name__,
                  "failure_reason": str(exc)[:200],
                  "youtube_private_hd": "NOT_UPLOADED",
                  "production_release_authorized": False}
    a.receipt.parent.mkdir(parents=True, exist_ok=True)
    a.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("RUN001_REAL_25MIN_MASTER_GATE=" + result["status"])
    print("YOUTUBE_PUBLIC_UPLOAD=FORBIDDEN")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
