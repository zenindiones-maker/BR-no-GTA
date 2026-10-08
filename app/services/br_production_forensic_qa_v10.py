"""BR-no-GTA V10: real MP4 audio/video technical QC before human publication.

Production is NEVER approved by this service. The reference is the approved
internal format contract, not an unlicensed third-party source. REA/Iris
observation is separated from actual creative authorization.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

SCHEMA = "BRProductionMediaForensicQA/v1"
PROFILE_CANARY = "synthetic_ci_canary"
PROFILE_MASTER = "br_no_gta_1080p_master"
VIDEO_CODECS = frozenset({"h264"})
AUDIO_CODECS = frozenset({"aac"})
MAX_JSON = 512_000
VOL_MEAN = re.compile(r"mean_volume:\s*(-?(?:[0-9]+(?:\.[0-9]+)?|inf))\s*dB", re.I)
BLACK_EVT = re.compile(r"black_start:\s*([0-9.]+)\s+black_end:\s*([0-9.]+)",re.I)
FREEZE_EVT = re.compile(r"freeze_start:\s*([0-9.]+)",re.I)
SILENCE_EVT = re.compile(r"silence_start:\s*([0-9.]+)",re.I)


def _sha256(path: Path) -> str:
    d=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            d.update(chunk)
    return d.hexdigest()


def _runner(argv: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, check=False, env={
                                  key: os.environ[key]
                                  for key in ("PATH","LANG","LC_ALL","HOME","TMPDIR")
                                  if key in os.environ
                              })
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("MEDIA_QA_TOOL_UNAVAILABLE_OR_TIMEOUT") from exc


def _positive_finite(value: Any) -> float | None:
    try:
        if isinstance(value,bool):return None
        number=float(value)
        return number if math.isfinite(number) and number>0 else None
    except (TypeError,ValueError,OverflowError):
        return None


def _fps(value: Any) -> float | None:
    try:
        fraction=Fraction(str(value))
        return float(fraction) if fraction>0 else None
    except (ValueError,ZeroDivisionError,TypeError):
        return None


def _windows(seconds: float, profile: str) -> list[tuple[float,float]]:
    if profile==PROFILE_CANARY:
        return [(0.0, min(2.0,seconds))]
    window=min(4.0,seconds)
    starts=[0.0,max(0,(seconds-window)/2),max(0,seconds-window)]
    return [(round(v,3),round(window,3)) for v in sorted(set(round(x,3) for x in starts))]


def _probe(path: Path) -> dict:
    result=_runner([
        "ffprobe","-v","error","-show_entries",
        "format=duration,format_name:stream=index,codec_type,codec_name,width,height,pix_fmt,avg_frame_rate,r_frame_rate,channels,sample_rate",
        "-of","json",str(path)],timeout=45)
    if result.returncode or len(result.stdout)>MAX_JSON:
        raise RuntimeError("MEDIA_QA_FFPROBE_FAILED")
    try:
        doc=json.loads(result.stdout)
    except (ValueError,TypeError) as exc:
        raise RuntimeError("MEDIA_QA_FFPROBE_INVALID_JSON") from exc
    if not isinstance(doc,dict) or not isinstance(doc.get("streams"),list):
        raise RuntimeError("MEDIA_QA_FFPROBE_INVALID_SCHEMA")
    return doc


def _assess_metadata(doc: dict, profile: str) -> tuple[list[str],dict]:
    streams=doc["streams"]
    videos=[s for s in streams if s.get("codec_type")=="video"]
    audios=[s for s in streams if s.get("codec_type")=="audio"]
    reasons=[]
    if len(videos)!=1:reasons.append("EXPECTED_ONE_VIDEO_STREAM")
    if len(audios)!=1:reasons.append("EXPECTED_ONE_AUDIO_STREAM")
    dur=_positive_finite(doc.get("format",{}).get("duration"))
    if dur is None:reasons.append("UNKNOWN_OR_INVALID_DURATION")
    elif profile==PROFILE_MASTER and not (1200<=dur<=1500):
        reasons.append("VIDEO_DURATION_NOT_20_TO_25_MINUTES")
    elif profile==PROFILE_CANARY and not (0.5<=dur<=10):
        reasons.append("CANARY_DURATION_OUTSIDE_BOUNDS")
    if videos:
        v=videos[0]
        expected=(1920,1080) if profile==PROFILE_MASTER else (320,180)
        if (v.get("width"),v.get("height"))!=expected:
            reasons.append("VIDEO_DIMENSIONS_INCORRECT")
        if v.get("codec_name") not in VIDEO_CODECS:
            reasons.append("VIDEO_CODEC_NOT_H264")
        if v.get("pix_fmt")!="yuv420p":
            reasons.append("VIDEO_PIXEL_FORMAT_NOT_YUV420P")
        fps=_fps(v.get("avg_frame_rate"))
        nominal=_fps(v.get("r_frame_rate"))
        if fps is None or abs(fps-30)>0.001:
            reasons.append("VIDEO_AVERAGE_FPS_NOT_30")
        if nominal is None or abs(nominal-30)>0.001:
            reasons.append("VIDEO_NOMINAL_FPS_NOT_30")
    if audios:
        a=audios[0]
        if a.get("codec_name") not in AUDIO_CODECS:
            reasons.append("AUDIO_CODEC_NOT_AAC")
        if a.get("channels")!=2:reasons.append("AUDIO_CHANNELS_NOT_STEREO")
        if str(a.get("sample_rate"))!="48000":
            reasons.append("AUDIO_SAMPLE_RATE_NOT_48KHZ")
    return reasons,{
        "duration_seconds":round(dur,3) if dur else None,
        "video_stream_count":len(videos),
        "audio_stream_count":len(audios),
        "video_codec":videos[0].get("codec_name") if videos else None,
        "audio_codec":audios[0].get("codec_name") if audios else None,
        "dimensions":[videos[0].get("width"),videos[0].get("height")] if videos else None,
        "fps":_fps(videos[0].get("avg_frame_rate")) if videos else None,
        "pixel_format":videos[0].get("pix_fmt") if videos else None,
    }


def _sample_window(path: Path,start:float,seconds:float) -> dict:
    # Both streams decoded into the null sink to detect demux/codec errors;
    # run individual bounded filters only AFTER structural validation.
    checks={}
    for stream in ("v","a"):
        cmd=["ffmpeg","-nostdin","-hide_banner","-v","error","-xerror",
             "-ss",str(start),"-i",str(path),"-t",str(seconds),
             "-map",f"0:{stream}:0","-f","null","-"]
        p=_runner(cmd,timeout=90)
        checks[f"{stream}_decode_ok"]=p.returncode==0
    volume=_runner(["ffmpeg","-nostdin","-hide_banner","-v","info",
                    "-ss",str(start),"-i",str(path),"-t",str(seconds),
                    "-map","0:a:0","-vn","-af","volumedetect","-f","null","-"],90)
    v=VOL_MEAN.search(volume.stderr)
    mean=None if v is None or v.group(1).lower() in ("-inf","inf") else float(v.group(1))
    checks["audio_mean_dbfs"]=mean
    checks["audio_measured"]=volume.returncode==0 and v is not None
    # Heuristics are annotations, not automatic creative judgment.
    detection=_runner(["ffmpeg","-nostdin","-hide_banner","-v","info",
        "-ss",str(start),"-i",str(path),"-t",str(seconds),
        "-map","0:v:0","-an","-vf","blackdetect=d=0.4:pix_th=0.10,freezedetect=n=-55dB:d=1",
        "-f","null","-"],90)
    checks["video_heuristic_filter_ok"]=detection.returncode==0
    checks["black_event_count"]=len(BLACK_EVT.findall(detection.stderr))
    checks["freeze_event_count"]=len(FREEZE_EVT.findall(detection.stderr))
    return checks


def analyze_render(path: str | Path,*,profile: str=PROFILE_MASTER) -> dict[str,Any]:
    if profile not in (PROFILE_CANARY,PROFILE_MASTER):
        raise ValueError("MEDIA_QA_PROFILE_UNSUPPORTED")
    source=Path(path)
    if (not source.is_absolute() or source.is_symlink() or not source.is_file()
        or source.suffix.lower()!=".mp4"):
        raise ValueError("MEDIA_QA_ABSOLUTE_REGULAR_MP4_REQUIRED")
    if source.stat().st_size<=1024:
        raise ValueError("MEDIA_QA_EMPTY_OR_TRUNCATED_MP4")
    reasons=[]
    doc=_probe(source)
    errors,metadata=_assess_metadata(doc,profile)
    reasons.extend(errors)
    windows=[]
    warnings=[]
    if not reasons:
        for start,seconds in _windows(metadata["duration_seconds"],profile):
            checked=_sample_window(source,start,seconds)
            windows.append({"start_seconds":start,"analyzed_seconds":seconds,**checked})
            if not checked["v_decode_ok"] or not checked["a_decode_ok"]:
                reasons.append("SAMPLED_MEDIA_DECODE_FAILED")
            if not checked["audio_measured"]:
                reasons.append("AUDIO_VOLUME_MEASUREMENT_FAILED")
            elif checked["audio_mean_dbfs"] is None or checked["audio_mean_dbfs"]<=-60:
                reasons.append("SAMPLED_AUDIO_SILENT_OR_TOO_LOW")
            if not checked["video_heuristic_filter_ok"]:
                reasons.append("VISUAL_HEURISTIC_FILTER_FAILED")
            if checked["black_event_count"] or checked["freeze_event_count"]:
                warnings.append("REVIEW_INTENTIONAL_BLACK_OR_STATIC_SHOTS")
    reasons=sorted(set(reasons))
    warnings=sorted(set(warnings))
    receipt={
        "schema_version":SCHEMA,
        "status":"TECHNICAL_SAMPLED_QA_PASS" if not reasons else "TECHNICAL_QA_FAIL",
        "profile":profile,
        "source_sha256":_sha256(source),
        "source_size_bytes":source.stat().st_size,
        "metadata":metadata,
        "sampled_windows":windows,
        "failure_codes":reasons,
        "review_warnings":warnings,
        "full_video_decode_verified":False,
        "full_audio_decode_verified":False,
        "voice_identity_verified":False,
        "voice_pronunciation_verified":False,
        "script_factual_accuracy_verified":False,
        "editorial_quality_verified":False,
        "human_review_approved":False,
        "artistic_approval":False,
        "publish_authorized":False,
        "harness_learning_write":"NOT_ATTEMPTED",
        "limitations":"Sampling and ffprobe do not prove full decode, identity, narration timing, absence of overlays, rights, or artistic quality. Requires private BR_OWNER_V1 and final human approval.",
    }
    receipt["receipt_sha256"]=hashlib.sha256(json.dumps(
        receipt,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()
    return receipt
