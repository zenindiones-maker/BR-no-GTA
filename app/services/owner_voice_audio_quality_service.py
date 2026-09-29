from __future__ import annotations

from array import array
import math
from pathlib import Path
import sys
import wave
from typing import Any, Mapping


PCM16_MAX = 32768.0
ACTIVE_SAMPLE_FRACTION = 0.015
CLIPPING_SAMPLE_FRACTION = 0.995


def _dbfs(value: float) -> float:
    if value <= 0.0:
        return -120.0
    return 20.0 * math.log10(min(1.0, value / PCM16_MAX))


def pcm16_quality_metrics(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    with wave.open(str(source), "rb") as handle:
        channels = int(handle.getnchannels())
        sample_width = int(handle.getsampwidth())
        sample_rate = int(handle.getframerate())
        frame_count = int(handle.getnframes())
        raw = handle.readframes(frame_count)

    if sample_width != 2:
        raise ValueError("OWNER_REFERENCE_PCM16_REQUIRED")
    if channels <= 0 or sample_rate <= 0 or frame_count <= 0:
        raise ValueError("OWNER_REFERENCE_AUDIO_INVALID")

    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        raise ValueError("OWNER_REFERENCE_AUDIO_EMPTY")

    absolute = [abs(int(value)) for value in samples]
    peak = max(absolute)
    square_mean = sum(float(value) * float(value) for value in samples) / len(samples)
    rms = math.sqrt(square_mean)

    active_threshold = int(PCM16_MAX * ACTIVE_SAMPLE_FRACTION)
    clipping_threshold = int(PCM16_MAX * CLIPPING_SAMPLE_FRACTION)
    active = sum(1 for value in absolute if value >= active_threshold)
    clipped = sum(1 for value in absolute if value >= clipping_threshold)

    duration = frame_count / float(sample_rate)
    speech_ratio = active / float(len(absolute))
    silence_ratio = 1.0 - speech_ratio
    return {
        "duration_seconds": duration,
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "peak_dbfs": _dbfs(float(peak)),
        "rms_dbfs": _dbfs(rms),
        "speech_ratio": max(0.0, min(1.0, speech_ratio)),
        "silence_ratio": max(0.0, min(1.0, silence_ratio)),
        "clipping_ratio": clipped / float(len(absolute)),
    }


def _bounded(value: float, low: float, high: float) -> float:
    if high <= low:
        raise ValueError("invalid score bounds")
    return max(0.0, min(1.0, (value - low) / (high - low)))


def score_owner_reference_quality(
    metrics: Mapping[str, Any],
    *,
    ptbr_probability: float,
    transcription_confidence: float,
) -> float:
    duration = float(metrics.get("duration_seconds") or 0.0)
    clipping = max(0.0, float(metrics.get("clipping_ratio") or 0.0))
    snr_db = float(metrics.get("snr_db") or 0.0)
    speech_ratio = float(metrics.get("speech_ratio") or 0.0)

    if 6.0 <= duration <= 10.0:
        duration_score = 1.0
    elif duration <= 0.0:
        duration_score = 0.0
    elif duration < 6.0:
        duration_score = _bounded(duration, 1.0, 6.0)
    else:
        duration_score = max(0.0, 1.0 - ((duration - 10.0) / 20.0))

    clipping_score = max(0.0, 1.0 - min(1.0, clipping / 0.02))
    snr_score = _bounded(snr_db, 8.0, 25.0)
    speech_score = 1.0 - min(1.0, abs(speech_ratio - 0.85) / 0.55)
    language_score = max(0.0, min(1.0, float(ptbr_probability)))
    transcript_score = max(0.0, min(1.0, float(transcription_confidence)))

    score = (
        0.16 * duration_score
        + 0.16 * clipping_score
        + 0.18 * snr_score
        + 0.12 * speech_score
        + 0.24 * language_score
        + 0.14 * transcript_score
    )
    return round(max(0.0, min(1.0, score)), 6)
