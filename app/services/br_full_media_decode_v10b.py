"""Optional whole-file FFmpeg decode integrity gate for owned BR-no-GTA MP4.

A sampled QA pass is a prerequisite. Full decode is an expensive separate
RESEARCH operation and never human, vocal-identity, legal or publish approval.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from app.services.br_production_forensic_qa_v10 import (
    SCHEMA as SAMPLED_SCHEMA, PROFILE_MASTER, PROFILE_CANARY,
    _sha256, _runner, _positive_finite,
)

SCHEMA="BRFullMediaDecodeEvidence/v1"
_ALLOWED_PROFILES=frozenset((PROFILE_MASTER,PROFILE_CANARY))
_FRAME=re.compile(r"^frame=(\d+)$",re.M)
_PROGRESS_END=re.compile(r"^progress=end$",re.M)
_OUT_US=re.compile(r"^out_time_us=(\d+)$",re.M)


def verify_full_decode(
    source: Path,
    sampled: dict[str,Any],
    *,
    timeout_seconds: int = 1200,
) -> dict[str,Any]:
    if type(timeout_seconds) is not int or not 30<=timeout_seconds<=1800:
        raise ValueError("FULL_DECODE_BUDGET_INVALID")
    if (not source.is_absolute() or not source.is_file() or source.is_symlink()
        or source.suffix.lower()!=".mp4"):
        raise ValueError("FULL_DECODE_SOURCE_INVALID")
    if not isinstance(sampled,dict) or sampled.get("schema_version")!=SAMPLED_SCHEMA:
        raise ValueError("FULL_DECODE_SAMPLED_EVIDENCE_INVALID")
    digest=sampled.get("receipt_sha256")
    expected=hashlib.sha256(json.dumps(
        {k:v for k,v in sampled.items() if k!="receipt_sha256"},
        sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()
    if digest!=expected or sampled.get("source_sha256")!=_sha256(source):
        raise ValueError("FULL_DECODE_SOURCE_OR_RECEIPT_DRIFT")
    if sampled.get("status")!="TECHNICAL_SAMPLED_QA_PASS":
        raise ValueError("FULL_DECODE_SAMPLED_QA_NOT_PASS")
    if (sampled.get("profile") not in _ALLOWED_PROFILES
        or sampled.get("publish_authorized") is not False
        or sampled.get("human_review_approved") is not False
        or sampled.get("voice_identity_verified") is not False):
        raise ValueError("FULL_DECODE_HUMAN_OR_PROFILE_BOUNDARY_INVALID")
    duration=_positive_finite(sampled.get("metadata",{}).get("duration_seconds"))
    if duration is None:
        raise ValueError("FULL_DECODE_DURATION_UNKNOWN")
    profile=sampled["profile"]
    if profile==PROFILE_MASTER and not 1200<=duration<=1500:
        raise ValueError("FULL_DECODE_LONGFORM_LENGTH_INVALID")
    if profile==PROFILE_CANARY and not 0.5<=duration<=10:
        raise ValueError("FULL_DECODE_CANARY_LENGTH_INVALID")
    cmd=[
        "ffmpeg","-nostdin","-hide_banner","-v","error","-xerror",
        "-threads","2","-i",str(source),"-map","0:v:0","-map","0:a:0",
        "-c:v","rawvideo","-c:a","pcm_s16le",
        "-progress","pipe:1","-f","null","-",
    ]
    out=_runner(cmd,timeout=timeout_seconds)
    report=(out.stdout or "")[:2_000_000]
    frames=[int(m) for m in _FRAME.findall(report)]
    progress_end=bool(_PROGRESS_END.search(report))
    timings=[int(m)/1_000_000 for m in _OUT_US.findall(report)]
    last_time=max(timings,default=0.0)
    # For a constant 30fps profile, frame count is an additional guard
    # against success with an incomplete video stream.
    expected_frames=int(math.floor(duration*30*0.99))
    frame_count=max(frames,default=0)
    checks={
        "ffmpeg_exit_zero":out.returncode==0,
        "progress_end":progress_end,
        "decoded_frames_at_least_99pct":frame_count>=expected_frames,
        "reported_time_at_least_98pct":last_time>=0.98*duration,
    }
    full=all(checks.values())
    result={
        "schema_version":SCHEMA,
        "status":"FULL_SYNTHETIC_CANARY_DECODE_PASS" if full and profile==PROFILE_CANARY
                 else "FULL_MASTER_TECHNICAL_DECODE_PASS" if full
                 else "FULL_DECODE_BLOCKED",
        "profile":profile,
        "source_sha256":sampled["source_sha256"],
        "sampled_qa_receipt_sha256":digest,
        "checks":checks,
        "expected_min_video_frames":expected_frames,
        "observed_video_frames":frame_count,
        "observed_max_media_time_seconds":round(last_time,3),
        "source_duration_seconds":duration,
        "entire_video_decoder_completed":full,
        "entire_audio_decoder_completed":full,
        "audio_identity_certified":False,
        "image_editorial_certified":False,
        "no_overlay_certified":False,
        "all_video_rights_certified":False,
        "can_authorize_render":False,
        "publish_authorized":False,
        "owner_human_approved":False,
        "runtime_cost":"MEASURE_ON_TARGET",
        "known_limitations":"FFmpeg null output checks decodability and completeness; it does not certify voice identity, artistic quality, overlay absence, lipsync or licensed provenance.",
    }
    result["evidence_sha256"]=hashlib.sha256(json.dumps(
        result,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()
    return result
