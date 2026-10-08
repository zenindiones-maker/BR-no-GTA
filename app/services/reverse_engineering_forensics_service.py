"""Forensic-only audiovisual measurement with explicit nonsemantic limitations.

All heavy work stays in FFmpeg; never upload media or mutate the input.
No analysis here proves speaker identity, originality, narrative quality or fitness.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Callable

from app.services.reverse_engineering_story_service import analyze_script_structure
from app.services.reverse_engineering_media_service import (
    ObservationError, _command, _source, analyze_reference,
)

SCHEMA = "BRAudiovisualForensics/v2"
MAX_MEDIA_SECONDS = 3600.0
MAX_EVENTS = 5000
LOUDNORM_JSON = re.compile(r'\{\s*"input_i"\s*:.*?\}', re.DOTALL)
NUMBER = r"-?(?:\d+(?:\.\d+)?|\.\d+)"
SILENCE_START = re.compile(r"silence_start:\s*(" + NUMBER + r")")
SILENCE_END = re.compile(r"silence_end:\s*(" + NUMBER + r")\s*\|\s*silence_duration:\s*(" + NUMBER + r")")
BLACK = re.compile(r"black_start:\s*(" + NUMBER + r")\s+black_end:\s*(" + NUMBER + r")\s+black_duration:\s*(" + NUMBER + r")")
FREEZE_START = re.compile(r"freeze_start:\s*(" + NUMBER + r")")
FREEZE_END = re.compile(r"freeze_end:\s*(" + NUMBER + r")")
MEDIA_EXTENSIONS = frozenset({".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".mp4", ".mov", ".mkv", ".webm"})
AUDIO_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh")
METRIC_UNITS = {"input_i": "LUFS", "input_tp": "dBTP", "input_lra": "LU", "input_thresh": "LUFS"}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return round(number, 3) if math.isfinite(number) else None


def _require_local_media(path: str | Path) -> Path:
    source = _source(path)
    if source.suffix.lower() not in MEDIA_EXTENSIONS:
        raise ObservationError("FORENSICS_MEDIA_FORMAT_FORBIDDEN")
    return source


def _ffmpeg_log(source: Path, *, filter_chain: str, has_video: bool, timeout: int = 300) -> str:
    # Positional arguments; no shell. Limits are enforced by the workflow as well.
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "info", "-i", str(source)]
    if has_video:
        command += ["-map", "0:v:0", "-vf", filter_chain, "-an"]
    else:
        command += ["-map", "0:a:0", "-af", filter_chain, "-vn"]
    command += ["-f", "null", "-"]
    result = _command(command, timeout=timeout)
    if len(result.stderr) > 4_000_000:
        raise ObservationError("FORENSICS_LOG_TOO_LARGE")
    return result.stderr


def _loudness(source: Path, *, timeout: int) -> dict[str, Any]:
    logs = _ffmpeg_log(
        source, filter_chain="loudnorm=I=-23:TP=-2:LRA=7:print_format=json",
        has_video=False, timeout=timeout,
    )
    matches = LOUDNORM_JSON.findall(logs)
    if not matches:
        raise ObservationError("FORENSICS_LOUDNESS_UNAVAILABLE")
    try:
        values = json.loads(matches[-1])
    except ValueError as exc:
        raise ObservationError("FORENSICS_LOUDNESS_PARSE_FAILED") from exc
    if not isinstance(values, dict) or not all(k in values for k in AUDIO_KEYS):
        raise ObservationError("FORENSICS_LOUDNESS_FIELDS_MISSING")
    measured = {
        key: {"value": _finite(values[key]), "unit": METRIC_UNITS[key]}
        for key in AUDIO_KEYS
    }
    return {
        "status": "MEASURED",
        "method": "FFmpeg_loudnorm_input_analysis_ITU_BS1770_EBU_R128",
        "metrics": measured,
        "note": "input metrics only; output stream discarded; not an automatic master target",
    }


def _silences(source: Path, *, timeout: int) -> dict[str, Any]:
    logs = _ffmpeg_log(
        source, filter_chain="silencedetect=noise=-40dB:d=0.25",
        has_video=False, timeout=timeout,
    )
    starts = [_finite(x) for x in SILENCE_START.findall(logs)]
    ends = [(_finite(x), _finite(duration)) for x, duration in SILENCE_END.findall(logs)]
    if len(starts) > MAX_EVENTS or len(ends) > MAX_EVENTS:
        raise ObservationError("FORENSICS_TOO_MANY_EVENTS")
    return {
        "status": "MEASURED", "method": "FFmpeg_silencedetect_-40dB_min_0.25s",
        "silence_start_seconds": starts,
        "silence_end_seconds": [row[0] for row in ends],
        "detected_duration_seconds": round(sum(duration for _, duration in ends if duration is not None), 3),
        "limitation": "threshold and encoding dependent; not semantic speech segmentation",
    }


def _video_events(source: Path, *, timeout: int) -> dict[str, Any]:
    black_log = _ffmpeg_log(
        source, filter_chain="blackdetect=d=0.20:pix_th=0.10",
        has_video=True, timeout=timeout,
    )
    segments = [
        {"start": _finite(start), "end": _finite(end), "duration": _finite(duration)}
        for start, end, duration in BLACK.findall(black_log)
    ]
    if len(segments) > MAX_EVENTS:
        raise ObservationError("FORENSICS_TOO_MANY_EVENTS")
    freeze_log = _ffmpeg_log(
        source, filter_chain="freezedetect=n=-60dB:d=0.5",
        has_video=True, timeout=timeout,
    )
    freezes = [_finite(x) for x in FREEZE_START.findall(freeze_log)]
    unfreezes = [_finite(x) for x in FREEZE_END.findall(freeze_log)]
    if len(freezes) > MAX_EVENTS or len(unfreezes) > MAX_EVENTS:
        raise ObservationError("FORENSICS_TOO_MANY_EVENTS")
    return {
        "status": "MEASURED",
        "black_segments": segments,
        "freeze_start_seconds": freezes,
        "freeze_end_seconds": unfreezes,
        "methods": ["FFmpeg_blackdetect_d0.20_pix_th0.10", "FFmpeg_freezedetect_n-60dB_d0.5"],
        "limitation": "dark intentional scenes and deliberate still frames can trigger events",
    }


def analyze_forensics(
    path: str | Path,
    *,
    rights: str,
    transcript: str | Path | None = None,
    include_scene_cuts: bool = False,
    timeout_per_pass_seconds: int = 300,
    include_audio_dynamics: bool = False,
    adaptive_shot_window_seconds: float | None = None,
) -> dict[str, Any]:
    """Closed-form evidence: errors never create synthetic PASS measurements."""
    if rights not in {"owned", "licensed", "observation_only"}:
        raise ObservationError("RIGHTS_ATTESTATION_REQUIRED")
    if not isinstance(timeout_per_pass_seconds, int) or not 5 <= timeout_per_pass_seconds <= 1200:
        raise ObservationError("FORENSICS_TIMEOUT_BOUNDS_INVALID")
    source = _require_local_media(path)
    # Preliminary probe before expensive decode; disallow unlimited durations.
    base = analyze_reference(source, rights=rights, transcript=transcript, scene_detection=False)
    streams = base["evidence"]["container_and_streams"]["streams"]
    duration = base["evidence"]["container_and_streams"]["duration_seconds"]
    if duration is None or not 0 < duration <= MAX_MEDIA_SECONDS:
        raise ObservationError("FORENSICS_DURATION_UNSUPPORTED")
    has_audio = any(stream["codec_type"] == "audio" for stream in streams)
    has_video = any(stream["codec_type"] == "video" for stream in streams)
    if not has_audio and not has_video:
        raise ObservationError("FORENSICS_NO_SUPPORTED_STREAMS")
    if type(include_audio_dynamics) is not bool:
        raise ObservationError("FORENSICS_AUDIO_DYNAMICS_FLAG_INVALID")
    if adaptive_shot_window_seconds is not None and (not isinstance(adaptive_shot_window_seconds, (int, float)) or type(adaptive_shot_window_seconds) is bool):
        raise ObservationError("FORENSICS_SHOT_WINDOW_FLAG_INVALID")
    audio = {
        "status": "MEASURED",
        "loudness": _loudness(source, timeout=timeout_per_pass_seconds),
        "silence": _silences(source, timeout=timeout_per_pass_seconds),
    } if has_audio else {"status": "NOT_APPLICABLE", "reason": "NO_AUDIO_STREAM"}
    if has_audio:
        if include_audio_dynamics:
            from app.services.reverse_engineering_audio_v3_service import analyze_audio_dynamics
            audio["dynamics"] = analyze_audio_dynamics(source, timeout_seconds=timeout_per_pass_seconds)
        else:
            audio["dynamics"] = {"status": "NOT_RUN"}
    video = _video_events(source, timeout=timeout_per_pass_seconds) if has_video else {
        "status": "NOT_APPLICABLE", "reason": "NO_VIDEO_STREAM",
    }
    if adaptive_shot_window_seconds is not None:
        if not has_video:
            raise ObservationError("FORENSICS_SHOT_VIDEO_REQUIRED")
        from app.services.reverse_engineering_scene_v3_service import analyze_shots
        video["adaptive_shots"] = analyze_shots(source, window_seconds=adaptive_shot_window_seconds)
    elif has_video:
        video["adaptive_shots"] = {"status": "NOT_RUN"}
    if include_scene_cuts and has_video:
        from app.services.reverse_engineering_media_service import detect_scene_cuts
        cut_times = detect_scene_cuts(source)
        video["candidate_cut_seconds"] = cut_times
        video["candidate_cuts_status"] = "MEASURED"
    else:
        video["candidate_cuts_status"] = "NOT_RUN"
    result = {
        "schema_version": SCHEMA,
        "source": base["source"],
        "base_observation_sha256": base["evidence_sha256"],
        "duration_seconds": duration,
        "audio": audio,
        "video": video,
        "transcript": base["evidence"]["script_timing"],
        "story_structure": analyze_script_structure(transcript, media_duration_seconds=duration) if transcript is not None else {"status": "NOT_PROVIDED"},
        "interpretation": {
            "status": "MEASUREMENTS_NOT_ARTISTIC_VERDICT",
            "speaker_identity_verified": False,
            "pronunciation_verified": False,
            "speech_transcribed": False,
            "human_approval_required": True,
        },
    }
    envelope = json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    result["evidence_sha256"] = hashlib.sha256(envelope.encode("utf-8")).hexdigest()
    return result


def differential_observation(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Structural comparisons only; candidate identity/originality never inferred."""
    if reference.get("schema_version") != SCHEMA or candidate.get("schema_version") != SCHEMA:
        raise ObservationError("FORENSICS_SCHEMA_MISMATCH")
    if reference.get("source", {}).get("rights") not in {"owned", "licensed", "observation_only"}:
        raise ObservationError("FORENSICS_REFERENCE_RIGHTS_UNVERIFIED")
    if candidate.get("source", {}).get("rights") not in {"owned", "licensed"}:
        raise ObservationError("FORENSICS_CANDIDATE_RIGHTS_UNVERIFIED")
    def value(o: dict[str, Any], key: str) -> float | None:
        return o.get("audio", {}).get("loudness", {}).get("metrics", {}).get(key, {}).get("value")
    differences: dict[str, float | None] = {}
    for key in ("input_i", "input_tp", "input_lra"):
        left, right = value(reference, key), value(candidate, key)
        differences[key] = round(right - left, 3) if (
            isinstance(left, (int, float)) and isinstance(right, (int, float))
        ) else None
    ref_duration = _finite(reference.get("duration_seconds"))
    can_duration = _finite(candidate.get("duration_seconds"))
    differences["duration_seconds"] = (
        round(can_duration - ref_duration, 3)
        if ref_duration is not None and can_duration is not None else None
    )
    return {
        "schema_version": "BRAudiovisualDifferential/v1",
        "reference_sha256": reference.get("source", {}).get("sha256"),
        "candidate_sha256": candidate.get("source", {}).get("sha256"),
        "metric_deltas_candidate_minus_reference": differences,
        "status": "DESCRIPTIVE_ONLY",
        "quality_pass": None,
        "human_review_required": True,
    }
