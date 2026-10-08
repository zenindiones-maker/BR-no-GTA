"""Calibrated source-only audio dynamics observer using FFmpeg astats.

No audio is written, mixed, normalized, cloned or sent externally.
These signal metrics do not establish intelligibility, emotional delivery or quality.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from app.services.reverse_engineering_media_service import ObservationError, _source, _sha256
from app.services.reverse_engineering_forensics_service import _ffmpeg_log, _finite

SCHEMA = "BRAudioDynamicsObservation/v1"
FIELDS = {
    "Peak level dB": "sample_peak_dbfs",
    "RMS level dB": "rms_dbfs",
    "DC offset": "dc_offset_linear",
    "Number of samples": "sample_count",
}


def _parse_overall(log: str) -> dict[str, float | None]:
    overall: dict[str, float | None] = {}
    in_overall = False
    for line in log.splitlines():
        # FFmpeg log format: [Parsed_astats_0 @ 0x...] Overall
        suffix = line.split("] ", 1)[-1].strip() if "] " in line else line.strip()
        if suffix == "Overall":
            in_overall = True
            overall = {}
            continue
        if not in_overall:
            continue
        if ":" not in suffix:
            continue
        name, _, raw_value = suffix.partition(":")
        if name in FIELDS:
            if name == "DC offset":
                try:
                    exact = float(raw_value.strip())
                except (ValueError, TypeError):
                    exact = float("nan")
                overall[FIELDS[name]] = round(exact, 8) if math.isfinite(exact) else None
            else:
                overall[FIELDS[name]] = _finite(raw_value.strip())
    if not all(field in overall for field in FIELDS.values()):
        raise ObservationError("AUDIO_ASTATS_OVERALL_MISSING")
    return overall


def analyze_audio_dynamics(path: str | Path, *, timeout_seconds: int = 300) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 5 <= timeout_seconds <= 1200:
        raise ObservationError("AUDIO_ASTATS_TIMEOUT_INVALID")
    source = _source(path)
    logs = _ffmpeg_log(
        source,
        filter_chain="astats=metadata=0:reset=0",
        has_video=False,
        timeout=timeout_seconds,
    )
    values = _parse_overall(logs)
    peak = values["sample_peak_dbfs"]
    rms = values["rms_dbfs"]
    if peak is not None and rms is not None and peak < rms:
        raise ObservationError("AUDIO_ASTATS_INVALID_PEAK_RMS")
    metrics = {
        "sample_peak_dbfs": {"value": peak, "unit": "dBFS"},
        "rms_dbfs": {"value": rms, "unit": "dBFS"},
        "crest_db": {"value": round(peak - rms, 3) if peak is not None and rms is not None else None, "unit": "dB"},
        "dc_offset_linear": {"value": values["dc_offset_linear"], "unit": "normalized_linear"},
        "crest_factor_linear": {"value": round(10 ** ((peak - rms) / 20), 6) if peak is not None and rms is not None else None, "unit": "ratio", "derivation": "10^(crest_db/20)"}
        "sample_count": {"value": values["sample_count"], "unit": "samples"},
    }
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": "MEASURED",
        "source_sha256": _sha256(source),
        "method": "FFmpeg_astats_overall_reset0",
        "metrics": metrics,
        "limitations": "sample peak is not true peak; RMS and crest are descriptive not perceptual mastering quality",
    }
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    receipt["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return receipt
