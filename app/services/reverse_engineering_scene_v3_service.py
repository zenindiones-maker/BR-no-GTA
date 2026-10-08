"""Independent bounded content/adaptive scene observation; never semantic scene recognition.

PySceneDetect is an optional, pinned BSD-licensed runtime, not an agent authority.
Only at most 90 seconds of a video can be inspected in one invocation.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any

from app.services.reverse_engineering_media_service import ObservationError, _source, probe_media

SCHEMA = "BRAdaptiveShotObservation/v1"
MAX_SECONDS_PER_PASS = 90.0
MAX_CUTS = 1000


def _clock(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    return f"{millis // 3600000:02d}:{(millis // 60000) % 60:02d}:{(millis // 1000) % 60:02d}.{millis % 1000:03d}"


def analyze_shots(
    path: str | Path, *,
    start_seconds: float = 0.0,
    window_seconds: float = 30.0,
    algorithm: str = "adaptive",
) -> dict[str, Any]:
    if algorithm not in {"adaptive", "content"}:
        raise ObservationError("SHOT_DETECTOR_UNSUPPORTED")
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (start_seconds, window_seconds)):
        raise ObservationError("SHOT_WINDOW_INVALID")
    if start_seconds < 0 or not 0 < window_seconds <= MAX_SECONDS_PER_PASS:
        raise ObservationError("SHOT_WINDOW_OUT_OF_BOUNDS")
    source = _source(path)
    metadata = probe_media(source)
    duration = metadata["duration_seconds"]
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise ObservationError("SHOT_DURATION_UNAVAILABLE")
    if not any(stream["codec_type"] == "video" for stream in metadata["streams"]):
        raise ObservationError("SHOT_VIDEO_REQUIRED")
    if start_seconds >= duration:
        raise ObservationError("SHOT_WINDOW_BEYOND_END")
    stop = min(duration, start_seconds + window_seconds)
    try:
        from scenedetect import AdaptiveDetector, ContentDetector, detect
    except ImportError as exc:
        raise ObservationError("SHOT_PYSCENEDETECT_NOT_INSTALLED") from exc
    detector = (
        AdaptiveDetector(adaptive_threshold=3.0, min_scene_len=10, min_content_val=12.0)
        if algorithm == "adaptive"
        else ContentDetector(threshold=27.0, min_scene_len=10)
    )
    try:
        # Scoped seek window, no splitting, no emitted frames and no output files.
        scenes = detect(
            str(source), detector, show_progress=False, backend="opencv",
            start_time=_clock(start_seconds), end_time=_clock(stop),
        )
    except Exception as exc:
        raise ObservationError("SHOT_DETECTOR_RUNTIME_FAILED") from exc
    if len(scenes) > MAX_CUTS + 1:
        raise ObservationError("SHOT_TOO_MANY_EVENTS")
    times = [
        round(scene[0].get_seconds(), 3)
        for scene in scenes[1:]
    ]
    if any(not start_seconds < t < stop for t in times):
        raise ObservationError("SHOT_TIMECODE_OUTSIDE_WINDOW")
    cut_times = sorted(set(times))
    boundaries = [round(start_seconds, 3), *cut_times, round(stop, 3)]
    shot_lengths = [round(b - a, 3) for a, b in zip(boundaries, boundaries[1:]) if b > a]
    result: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "MEASURED",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest() if source.stat().st_size <= 4_000_000 else None,
        "algorithm": f"PySceneDetect_0.7.1_{algorithm}",
        "start_seconds": round(start_seconds, 3),
        "stop_seconds": round(stop, 3),
        "coverage_seconds": round(stop - start_seconds, 3),
        "total_duration_seconds": duration,
        "full_duration_covered": start_seconds == 0.0 and stop >= duration,
        "cut_candidates_seconds": cut_times,
        "cut_count": len(cut_times),
        "median_shot_seconds_in_window": round(statistics.median(shot_lengths), 3) if shot_lengths else None,
        "limits": "shot candidates; camera movement, effects and fade transitions require independent review",
    }
    canonical = json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    result["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return result
