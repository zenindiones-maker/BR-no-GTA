"""Reconstruction fidelity probes for ORIGINAL/explicitly licensed comparable sources.

Strict technical aligned-reference evaluation. No media creation, waveform export,
voice identification, bypass, similarity score for unrelated content or publishing.
FFmpeg and numpy are used only for bounded signal analysis.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from app.services.reverse_engineering_media_service import (
    ObservationError, _sha256, _source, probe_media,
)

SCHEMA = "BRReconstructionFidelity/v1"
MAX_WINDOW_SECONDS = 12.0
PCM_HZ = 16000
PCM_MAX_BYTES = int(MAX_WINDOW_SECONDS * PCM_HZ * 4) + 4096
LOG_MAX_CHARS = 2_000_000
PSNR_FRAME = re.compile(r"\bn:(\d+)\s+mse_avg:([0-9.]+)\s+")
SSIM_FRAME = re.compile(r"\bn:(\d+).*?\bAll:([0-9.]+)\b")
PSNR_AVERAGE = re.compile(r"\bpsnr_avg:([0-9.]+|inf)\b", re.IGNORECASE)


def _time(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= MAX_WINDOW_SECONDS:
        raise ObservationError("FIDELITY_WINDOW_UNSUPPORTED")
    return float(value)


def _call(args: list[str], *, timeout: int = 150, binary: bool = False) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, text=not binary,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("FIDELITY_MEASUREMENT_UNAVAILABLE") from exc
    if result.returncode != 0:
        raise ObservationError("FIDELITY_MEASUREMENT_FAILED")
    output_length = len(result.stdout) + len(result.stderr)
    if output_length > (PCM_MAX_BYTES + LOG_MAX_CHARS if binary else LOG_MAX_CHARS):
        raise ObservationError("FIDELITY_OUTPUT_BOUNDS_EXCEEDED")
    return result


def _stream(probe: dict, kind: str) -> dict | None:
    return next((s for s in probe["streams"] if s.get("codec_type") == kind), None)


def _fps(stream: dict) -> Fraction:
    try:
        n = Fraction(str(stream["avg_frame_rate"]))
        r = Fraction(str(stream["r_frame_rate"]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ObservationError("FIDELITY_FRAME_RATE_UNVERIFIED") from exc
    if n <= 0 or n > 120 or n != r:
        raise ObservationError("FIDELITY_FRAME_RATE_MISMATCH_OR_VFR")
    return n


def _checked_metadata(reference: Path, candidate: Path, *, window_seconds: float) -> tuple[dict, dict]:
    ref = probe_media(reference)
    can = probe_media(candidate)
    rd, cd = ref.get("duration_seconds"), can.get("duration_seconds")
    if rd is None or cd is None or rd <= 0 or cd <= 0 or min(rd, cd) < window_seconds - 0.005:
        raise ObservationError("FIDELITY_INCOMPLETE_SOURCE_WINDOW")
    return ref, can


def _video(reference: Path, candidate: Path, *, refprobe: dict,
           canprobe: dict, seconds: float) -> dict:
    r = _stream(refprobe, "video")
    c = _stream(canprobe, "video")
    if r is None or c is None:
        return {"status": "NOT_APPLICABLE", "reason": "BOTH_VIDEO_STREAMS_REQUIRED"}
    if not all(isinstance(s.get("width"), int) and isinstance(s.get("height"), int) for s in (r, c)):
        raise ObservationError("FIDELITY_DIMENSIONS_UNKNOWN")
    if (r["width"], r["height"]) != (c["width"], c["height"]):
        raise ObservationError("FIDELITY_RESOLUTION_MISMATCH_REQUIRES_EXPLICIT_CONFORM")
    fps = _fps(r)
    if _fps(c) != fps:
        raise ObservationError("FIDELITY_FPS_MISMATCH_REQUIRES_EXPLICIT_CONFORM")
    # Comparing same timestamp, no auto-scaling, interpolation or temporal warp.
    if abs(refprobe["duration_seconds"] - canprobe["duration_seconds"]) > 0.5 / float(fps):
        raise ObservationError("FIDELITY_VIDEO_DURATION_MISMATCH")
    windows = (
        f"[0:v]trim=start=0:duration={seconds:.3f},settb=AVTB,setpts=PTS-STARTPTS,"
        "format=yuv420p[reference];"
        f"[1:v]trim=start=0:duration={seconds:.3f},settb=AVTB,setpts=PTS-STARTPTS,"
        "format=yuv420p[candidate];"
    )
    out = {}
    for name in ("psnr", "ssim"):
        graph = windows + f"[candidate][reference]{name}=stats_file=-[out]"
        result = _call([
            "ffmpeg", "-nostdin", "-hide_banner", "-v", "info",
            "-i", str(reference), "-i", str(candidate),
            "-filter_complex_threads", "1",
            "-filter_complex", graph, "-map", "[out]", "-an", "-f", "null", "-"
        ])
        if name == "psnr":
            frames = [(int(i), float(mse)) for i, mse in PSNR_FRAME.findall(result.stdout)]
            if not frames:
                raise ObservationError("FIDELITY_PSNR_NOT_MEASURED")
            average = PSNR_AVERAGE.search(result.stdout)
            # ffmpeg summary usually logged to stderr; use per-frame MSE as
            # primary robust measure even when average dB=inf.
            mean_mse = sum(v for _, v in frames) / len(frames)
            out["mean_squared_pixel_error"] = round(mean_mse, 6)
            out["lossless_pixel_match"] = all(v == 0 for _, v in frames)
        else:
            frames = [(int(i), float(value)) for i, value in SSIM_FRAME.findall(result.stdout)]
            if not frames:
                raise ObservationError("FIDELITY_SSIM_NOT_MEASURED")
            out["mean_frame_ssim"] = round(sum(v for _, v in frames) / len(frames), 6)
        numbers = [i for i, _ in frames]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ObservationError("FIDELITY_FRAME_INDEX_GAP")
        out[f"{name}_compared_frames"] = len(frames)
    if out["psnr_compared_frames"] != out["ssim_compared_frames"]:
        raise ObservationError("FIDELITY_FRAME_COUNT_CONFLICT")
    expected = seconds * float(fps)
    if abs(out["psnr_compared_frames"] - expected) > 1.05:
        raise ObservationError("FIDELITY_VIDEO_COVERAGE_INCOMPLETE")
    return {
        "status": "MEASURED",
        "method": "FFmpeg_ssim_psnr_frame_aligned_yuv420p",
        "fps": f"{fps.numerator}/{fps.denominator}",
        "width": r["width"], "height": r["height"],
        **out,
        "limitations": "Only same-content frame alignment, not semantic animation reconstruction; color quantization in yuv420p",
    }


def _pcm(path: Path, seconds: float):
    try:
        import numpy as np
    except ImportError as exc:
        raise ObservationError("FIDELITY_NUMPY_REQUIRED") from exc
    result = _call([
        "ffmpeg", "-nostdin", "-hide_banner", "-v", "error",
        "-i", str(path), "-map", "0:a:0",
        "-t", f"{seconds:.3f}", "-ac", "1", "-ar", str(PCM_HZ),
        "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1",
    ], binary=True)
    if len(result.stdout) > PCM_MAX_BYTES or len(result.stdout) % 4:
        raise ObservationError("FIDELITY_PCM_INVALID")
    samples = np.frombuffer(result.stdout, dtype="<f4").astype("float64")
    if not len(samples) or not np.isfinite(samples).all():
        raise ObservationError("FIDELITY_PCM_EMPTY_OR_NONFINITE")
    return samples


def _audio(reference: Path, candidate: Path, *, refprobe: dict,
           canprobe: dict, seconds: float) -> dict:
    ra, ca = _stream(refprobe, "audio"), _stream(canprobe, "audio")
    if ra is None or ca is None:
        return {"status": "NOT_APPLICABLE", "reason": "BOTH_AUDIO_STREAMS_REQUIRED"}
    import numpy as np
    x, y = _pcm(reference, seconds), _pcm(candidate, seconds)
    expected = int(seconds * PCM_HZ)
    if min(len(x), len(y)) < expected - 2 or abs(len(x) - len(y)) > 2:
        raise ObservationError("FIDELITY_AUDIO_COVERAGE_OR_ALIGNMENT_MISMATCH")
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    px, py = float(np.dot(x, x)), float(np.dot(y, y))
    silence = px <= 1e-12 and py <= 1e-12
    norm_corr = (float(np.dot(x, y)) / math.sqrt(px * py)) if px > 1e-12 and py > 1e-12 else None
    raw_rmse = float(np.sqrt(np.mean((x - y)**2)))
    ratio = math.sqrt(py / px) if px > 1e-12 else None
    # Correlation is not speech identity. Do not fit delay/amplitude then claim
    # "perfect"; always expose unadjusted absolute signal difference.
    diagnostic = ("BOTH_EFFECTIVELY_SILENT" if silence
                  else "REFERENCE_SILENT" if px <= 1e-12
                  else "CANDIDATE_SILENT" if py <= 1e-12
                  else "NONIDENTICAL_WAVEFORM" if raw_rmse > 1e-7
                  else "PCM_MATCH_WITHIN_NUMERICAL_PRECISION")
    return {
        "status": "MEASURED", "method": "FFmpeg_pcm_f32le_mono_16000_time_aligned",
        "sample_count": n,
        "normalized_correlation": round(norm_corr, 6) if norm_corr is not None else None,
        "candidate_to_reference_rms_ratio": round(ratio, 6) if ratio is not None else None,
        "unadjusted_difference_rmse_linear": round(raw_rmse, 9),
        "waveform_bit_equivalent_after_decode": bool(np.array_equal(x, y)),
        "diagnostic": diagnostic,
        "limitations": "Stereo downmix hides phase and spatial changes; no speaker, prosody, emotion, intelligibility, lip sync or pronunciation certification",
    }


def compare_reconstruction(reference: str | Path, candidate: str | Path, *,
                           rights: str, candidate_rights: str,
                           window_seconds: float = 2.0) -> dict[str, Any]:
    if rights not in {"owned", "licensed"} or candidate_rights not in {"owned", "licensed"}:
        raise ObservationError("FIDELITY_COPY_RIGHTS_NOT_ESTABLISHED")
    seconds = _time(window_seconds)
    ref, can = _source(reference), _source(candidate)
    if ref == can:
        raise ObservationError("FIDELITY_IDENTICAL_SOURCE_PATH_NOT_A_RECONSTRUCTION")
    refprobe, canprobe = _checked_metadata(ref, can, window_seconds=seconds)
    vid = _video(ref, can, refprobe=refprobe, canprobe=canprobe, seconds=seconds)
    aud = _audio(ref, can, refprobe=refprobe, canprobe=canprobe, seconds=seconds)
    if vid["status"] != "MEASURED" and aud["status"] != "MEASURED":
        raise ObservationError("FIDELITY_NO_COMPARABLE_STREAMS")
    observations = []
    if vid["status"] == "MEASURED":
        if not vid["lossless_pixel_match"]:
            observations.append("FRAME_DIFFERENCE_REVIEW_EDIT_RENDER_CODEC_AND_TIMING")
    if aud["status"] == "MEASURED":
        if not aud["waveform_bit_equivalent_after_decode"]:
            observations.append("WAVEFORM_DIFFERENCE_REVIEW_TIMING_GAIN_AND_MIX")
    receipt = {
        "schema_version": SCHEMA,
        "status": "TECHNICAL_MEASUREMENT_ONLY",
        "source": {"sha256": _sha256(ref), "rights": rights},
        "candidate": {"sha256": _sha256(can), "rights": candidate_rights},
        "window_seconds": seconds,
        "full_duration_analyzed": (
            abs(refprobe["duration_seconds"] - seconds) <= 0.005
            and abs(canprobe["duration_seconds"] - seconds) <= 0.005
        ),
        "video": vid, "audio": aud, "difference_classes": observations,
        "fidelity_scope": "ALIGNED_TECHNICAL_SIGNAL_ONLY",
        "identity_verified": False, "artistic_equivalence_verified": False,
        "right_to_reproduce_verified_independently": False,
        "publication_authorized": False, "quality_approved": False,
        "harness_learning_write": "NOT_ATTEMPTED",
    }
    canonical = json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    receipt["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return receipt
