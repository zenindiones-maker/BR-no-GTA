"""V16 bounded, real decoded scene-transition observation (not semantic vision).

Use only after the existing persisted Harness authorization admits an owned MP4.
No raw frame export, pretrained vision model, decoded target instructions, OCR,
voice reference access, publication, or unbounded processing.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA="BRHarnessVisualTimelineEvidence/v1"
MAX_WINDOWS=3
WINDOW_SECONDS=8.0
THRESHOLD=0.18
PTS=re.compile(r"pts_time:\s*(-?\d+(?:\.\d+)?)")
SHOWINFO_LINE=re.compile(r"\bParsed_showinfo_")
MAX_OUTPUT=250_000


def _windows(duration: float) -> tuple[float,...]:
    if not isinstance(duration,(int,float)) or isinstance(duration,bool):
        raise ValueError("TIMELINE_DURATION_INVALID")
    if not math.isfinite(float(duration)) or not 0.5<=duration<=1800:
        raise ValueError("TIMELINE_DURATION_OUT_OF_SCOPE")
    if duration<=WINDOW_SECONDS:
        return (0.0,)
    cap=duration-WINDOW_SECONDS
    return tuple(sorted(set(round(x,3) for x in (0.0,cap/2,cap))))


def _measure_window(path:Path, start:float, seconds:float,
                    *,timeout_seconds:int=75)->dict[str,Any]:
    if type(timeout_seconds) is not int or not 5<=timeout_seconds<=90:
        raise ValueError("TIMELINE_TIMEOUT_INVALID")
    # FFmpeg filter syntax escapes the comma inside gt(scene, threshold).
    cmd=[
        "ffmpeg","-nostdin","-hide_banner","-v","info","-xerror",
        "-ss",f"{start:.3f}","-i",str(path),"-t",f"{seconds:.3f}",
        "-map","0:v:0","-an","-vf",
        r"select='gt(scene\,0.18)',showinfo",
        "-f","null","-",
    ]
    env={k:os.environ[k] for k in ("PATH","LANG","LC_ALL","HOME","TMPDIR") if k in os.environ}
    try:
        p=subprocess.run(cmd,env=env,check=False,capture_output=True,
                         text=True,timeout=timeout_seconds)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise RuntimeError("TIMELINE_FFMPEG_UNAVAILABLE_OR_TIMEOUT") from exc
    if p.returncode!=0 or len(p.stderr)>MAX_OUTPUT or len(p.stdout)>MAX_OUTPUT:
        raise RuntimeError("TIMELINE_FFMPEG_DECODE_OR_OUTPUT_FAILED")
    found=[]
    for line in p.stderr.splitlines():
        if not SHOWINFO_LINE.search(line):
            continue
        m=PTS.search(line)
        if m:
            t=float(m.group(1))
            if math.isfinite(t) and 0<=t<=seconds+0.2:
                found.append(round(start+t,3))
    return {
        "start_seconds":round(start,3),
        "analyzed_seconds":round(seconds,3),
        "candidate_transition_seconds":sorted(set(found))[:200],
        "candidate_transitions_count":len(set(found)),
        "decode_exit_zero":True,
    }


def observe_timeline(*,source:Path,authoritative_pixel_evidence:dict[str,Any],
                     timeout_seconds:int=75)->dict[str,Any]:
    """Actual content-change detections from same SHA as scoped pixel evidence."""
    from app.services.br_harness_sensory_pixel_v12 import _checked_source,_sha
    _checked_source(source,"owner_video_mp4")
    if (not isinstance(authoritative_pixel_evidence,dict)
        or authoritative_pixel_evidence.get("schema_version")!="BRHarnessSensoryPixelObservation/v1"
        or authoritative_pixel_evidence.get("media_kind")!="owner_video_mp4"
        or authoritative_pixel_evidence.get("status")!="PIXELS_DECODED_AND_MEASURED"
        or authoritative_pixel_evidence.get("source_sha256")!=_sha(source)):
        raise PermissionError("TIMELINE_REQUIRES_SAME_SOURCE_PIXELS")
    meta=authoritative_pixel_evidence.get("media_metadata")
    if not isinstance(meta,dict):
        raise ValueError("TIMELINE_DURATION_MISSING")
    duration=meta.get("duration_seconds")
    starts=_windows(duration)
    windows=[_measure_window(source,start,min(WINDOW_SECONDS,duration-start),
                             timeout_seconds=timeout_seconds) for start in starts]
    all_times=sorted(set(t for w in windows for t in w["candidate_transition_seconds"]))
    report={
        "schema_version":SCHEMA,
        "status":"SCOPED_VIDEO_TRANSITIONS_MEASURED",
        "source_sha256":authoritative_pixel_evidence["source_sha256"],
        "pixel_receipt_sha256":authoritative_pixel_evidence.get("receipt_sha256"),
        "window_count":len(windows),
        "window_seconds_max":WINDOW_SECONDS,
        "detector":"FFmpeg select gt(scene,0.18) + showinfo; sampled windows",
        "candidate_transition_times_seconds":all_times[:600],
        "candidate_transition_count":len(all_times),
        "windows":windows,
        "whole_video_scenes_certified":False,
        "semantically_interpreted":False,
        "artist_recognition_certified":False,
        "subtitle_absence_certified":False,
        "audio_transcript_certified":False,
        "owner_identity_certified":False,
        "automated_editorial_pass":False,
        "publisher_authorized":False,
        "mcp_authority_granted":False,
        "raw_frame_payload_included":False,
        "limitations":"Only candidate cuts from decoded pixels in bounded temporal windows, not global scene coverage, script-to-scene matching or artistic quality.",
    }
    report["sha256"]=hashlib.sha256(json.dumps(report,sort_keys=True,
        ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()).hexdigest()
    return report
