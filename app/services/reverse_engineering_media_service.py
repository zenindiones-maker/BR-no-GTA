"""Read-only audiovisual evidence extraction for BR-no-GTA.

This is not a TTS engine, script copier, publisher, or independent agent.
No external network, models, file mutation, or implicit discovery occurs.
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "BRReverseEngineeringObservation/v1"
RIGHTS = frozenset({"owned", "licensed", "observation_only"})
TIME_RE = re.compile(r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})")
CUT_RE = re.compile(r"\bpts_time:(-?\d+(?:\.\d+)?)")
MAX_PROBE_BYTES = 5_000_000


class ObservationError(ValueError):
    """A reference or external-tool result did not satisfy the evidence contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source(path: str | Path, *, allowed_suffixes: tuple[str, ...] | None = None) -> Path:
    source = Path(path).expanduser()
    if not source.is_file() or source.is_symlink():
        raise ObservationError("SOURCE_MISSING_OR_SYMLINK")
    if allowed_suffixes and source.suffix.lower() not in allowed_suffixes:
        raise ObservationError("SOURCE_FORMAT_NOT_SUPPORTED")
    return source.resolve(strict=True)


def _command(args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        outcome = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("OBSERVATION_TOOL_UNAVAILABLE_OR_TIMEOUT") from exc
    if outcome.returncode != 0:
        raise ObservationError("OBSERVATION_TOOL_FAILED")
    return outcome


def probe_media(path: str | Path) -> dict[str, Any]:
    """Get measurable container/stream properties using ffprobe; never infer missing values."""
    source = _source(path)
    result = _command(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)],
        timeout=45,
    )
    if len(result.stdout.encode("utf-8")) > MAX_PROBE_BYTES:
        raise ObservationError("FFPROBE_OUTPUT_TOO_LARGE")
    try:
        value = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ObservationError("FFPROBE_INVALID_JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("streams"), list):
        raise ObservationError("FFPROBE_MISSING_STREAMS")
    streams = []
    for raw in value["streams"]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("codec_type", "unknown"))
        if kind not in {"audio", "video"}:
            continue
        keys = (
            "codec_type", "codec_name", "width", "height", "sample_rate",
            "channels", "channel_layout", "r_frame_rate", "avg_frame_rate", "duration",
        )
        streams.append({key: raw[key] for key in keys if key in raw})
    if not streams:
        raise ObservationError("FFPROBE_NO_AUDIO_OR_VIDEO")
    raw_duration = value.get("format", {}).get("duration")
    try:
        duration = round(float(raw_duration), 3) if raw_duration is not None else None
    except (ValueError, TypeError):
        duration = None
    if duration is not None and (not (0 <= duration < float("inf"))):
        duration = None
    return {"duration_seconds": duration, "streams": streams}


def _seconds(timecode: str) -> float:
    match = TIME_RE.fullmatch(timecode.strip())
    if not match:
        raise ObservationError("TIMECODE_INVALID")
    return (
        int(match["h"]) * 3600 + int(match["m"]) * 60
        + int(match["s"]) + int(match["ms"]) / 1000
    )


def observe_transcript(path: str | Path) -> dict[str, Any]:
    """Only analyze authorized local text; do not retain copied dialogue in a receipt."""
    source = _source(path, allowed_suffixes=(".srt", ".txt"))
    if source.stat().st_size > 5_000_000:
        raise ObservationError("TRANSCRIPT_TOO_LARGE")
    text = source.read_text(encoding="utf-8-sig")
    if source.suffix.lower() == ".txt":
        paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
        words = re.findall(r"\b[\wÀ-ÿ]+(?:['’][\wÀ-ÿ]+)?\b", text)
        return {
            "kind": "untimed_script", "word_count": len(words),
            "paragraph_count": len(paragraphs),
            "mean_words_per_paragraph": (
                round(len(words) / len(paragraphs), 2) if paragraphs else None
            ),
            "words_per_minute": None,
            "timing_observed": False,
            "sha256": _sha256(source),
        }
    cues: list[tuple[float, float, int]] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        timing = next((line for line in lines if "-->" in line), None)
        if not timing:
            continue
        start_text, end_text = timing.split("-->", 1)
        start = _seconds(start_text)
        end = _seconds(end_text.split()[0])
        if end <= start:
            raise ObservationError("TRANSCRIPT_INVALID_CUE_INTERVAL")
        index = lines.index(timing)
        dialogue = " ".join(lines[index + 1 :])
        words = re.findall(r"\b[\wÀ-ÿ]+(?:['’][\wÀ-ÿ]+)?\b", dialogue)
        cues.append((start, end, len(words)))
    if not cues:
        raise ObservationError("TRANSCRIPT_NO_TIMED_CUES")
    if any(next_cue[0] < prior[0] for prior, next_cue in zip(cues, cues[1:])):
        raise ObservationError("TRANSCRIPT_CUES_OUT_OF_ORDER")
    span = max(end for _, end, _ in cues) - min(start for start, _, _ in cues)
    total = sum(n for _, _, n in cues)
    return {
        "kind": "timed_subtitles", "cue_count": len(cues),
        "word_count": total, "timing_observed": True,
        "observed_span_seconds": round(span, 3),
        "words_per_minute": round(60 * total / span, 2) if span > 0 else None,
        "sha256": _sha256(source),
    }


def detect_scene_cuts(path: str | Path, *, threshold: float = 0.35) -> list[float]:
    """Optional full video decode: scene-change candidates, NOT editorial scene semantics."""
    source = _source(path)
    if not 0.01 <= threshold <= 0.99:
        raise ObservationError("SCENE_THRESHOLD_INVALID")
    expr = f"select=gt(scene\\,{threshold:.3f}),showinfo"
    outcome = _command(
        ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(source),
         "-vf", expr, "-an", "-f", "null", "-"],
        timeout=1200,
    )
    cuts = sorted({
        round(float(v), 3) for v in CUT_RE.findall(outcome.stderr)
        if float(v) >= 0
    })
    return cuts


def analyze_reference(
    path: str | Path,
    *,
    rights: str,
    transcript: str | Path | None = None,
    scene_detection: bool = False,
) -> dict[str, Any]:
    if rights not in RIGHTS:
        raise ObservationError("RIGHTS_ATTESTATION_REQUIRED")
    source = _source(path)
    media = probe_media(source)
    has_video = any(x["codec_type"] == "video" for x in media["streams"])
    if scene_detection and not has_video:
        raise ObservationError("SCENE_DETECTION_REQUIRES_VIDEO")
    cuts = detect_scene_cuts(source) if scene_detection else None
    script = observe_transcript(transcript) if transcript is not None else None
    duration = media["duration_seconds"]
    lengths = None
    if cuts is not None and duration is not None:
        boundaries = [0.0] + [v for v in cuts if 0 < v < duration] + [duration]
        lengths = [round(b - a, 3) for a, b in zip(boundaries, boundaries[1:]) if b > a]
    observations: dict[str, Any] = {
        "schema_version": SCHEMA,
        "source": {"filename": source.name, "sha256": _sha256(source), "rights": rights},
        "evidence": {
            "container_and_streams": {"status": "MEASURED", **media},
            "scene_cuts": {
                "status": "MEASURED" if cuts is not None else "NOT_RUN",
                "candidate_cut_seconds": cuts,
                "median_shot_seconds": round(statistics.median(lengths), 3) if lengths else None,
                "detector": "ffmpeg_select_scene_0.35" if cuts is not None else None,
            },
            "script_timing": {"status": "MEASURED", **script} if script else {"status": "NOT_PROVIDED"},
        },
        "reconstruction": {
            "allowed": rights in {"owned", "licensed"},
            "status": "REFERENCE_EVIDENCE_ONLY",
            "requires_original_expression": True,
            "human_quality_approval_required": True,
        },
    }
    canonical = json.dumps(observations, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    observations["evidence_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return observations
