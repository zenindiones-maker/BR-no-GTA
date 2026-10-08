"""Studio forensic specialists: stems, animation motion, external alignment QA, OTIO.

Read-only, bounded and explicitly unable to access the private owner-voice plane.
No generation, voice cloning, publishing, model downloads, or memory writes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

from app.services.reverse_engineering_media_service import ObservationError, _sha256, _source, probe_media

MAX_STEMS = 4
MAX_SECONDS = 8
RATE = 16000
MAX_VIDEO_FRAMES = 48
ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")


def _digest(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _read_json(path: str | Path, *, max_bytes: int = 256_000) -> dict:
    src = _source(path, allowed_suffixes=(".json",))
    if src.stat().st_size > max_bytes:
        raise ObservationError("STUDIO_INPUT_TOO_LARGE")
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise ObservationError("STUDIO_INPUT_INVALID_JSON") from exc
    if not isinstance(data, dict):
        raise ObservationError("STUDIO_INPUT_SCHEMA_INVALID")
    return data


def _f32_stereo(path: Path, seconds: int):
    try:
        import numpy as np
    except ImportError as exc:
        raise ObservationError("STUDIO_NUMPY_NOT_INSTALLED") from exc
    argv = [
        "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-t", str(seconds), "-ac", "2", "-ar", str(RATE),
        "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1",
    ]
    try:
        run = subprocess.run(argv, capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("STUDIO_STEM_FFMPEG_UNAVAILABLE") from exc
    max_bytes = seconds * RATE * 8 + 4096
    if run.returncode or not run.stdout or len(run.stdout) > max_bytes or len(run.stdout) % 8:
        raise ObservationError("STUDIO_STEM_DECODE_FAILED")
    samples = np.frombuffer(run.stdout, dtype="<f4").astype("float64").reshape(-1, 2)
    if not np.isfinite(samples).all():
        raise ObservationError("STUDIO_STEM_NONFINITE")
    if abs(len(samples) - RATE * seconds) > 3:
        raise ObservationError("STUDIO_STEM_INCOMPLETE_WINDOW")
    return samples


def analyze_stems(paths: list[str | Path], *, window_seconds: int = 2) -> dict[str, Any]:
    if not isinstance(paths, list) or not 2 <= len(paths) <= MAX_STEMS:
        raise ObservationError("STUDIO_STEMS_COUNT_INVALID")
    if type(window_seconds) is not int or not 1 <= window_seconds <= MAX_SECONDS:
        raise ObservationError("STUDIO_STEM_WINDOW_INVALID")
    sources = [_source(p, allowed_suffixes=(".wav", ".flac", ".m4a", ".mp3")) for p in paths]
    if len(set(sources)) != len(sources):
        raise ObservationError("STUDIO_DUPLICATED_STEM")
    streams = [probe_media(src) for src in sources]
    for probe in streams:
        audio = next((s for s in probe["streams"] if s.get("codec_type") == "audio"), None)
        if audio is None or probe["duration_seconds"] is None or probe["duration_seconds"] < window_seconds - 0.005:
            raise ObservationError("STUDIO_STEM_AUDIO_OR_DURATION_MISSING")
        # Measuring stereo image requires stereo sources; mono is allowed but
        # will be explicitly marked duplicated during a stereo decode.
        if audio.get("channels") not in (1, 2):
            raise ObservationError("STUDIO_STEM_SURROUND_REQUIRES_SEPARATE_GATE")
    import numpy as np
    samples = [_f32_stereo(src, window_seconds) for src in sources]
    n = min(len(x) for x in samples)
    result_stems = []
    for src, probe, decoded in zip(sources, streams, samples):
        x = decoded[:n]
        peak = float(np.max(np.abs(x)))
        rms = float(np.sqrt(np.mean(x*x)))
        left, right = x[:,0], x[:,1]
        lsd, rsd = float(np.std(left)), float(np.std(right))
        correlation = float(np.corrcoef(left, right)[0,1]) if lsd > 1e-9 and rsd > 1e-9 else None
        result_stems.append({
            "sha256": _sha256(src),
            "input_channels": next(s["channels"] for s in probe["streams"] if s["codec_type"]=="audio"),
            "sample_peak_dbfs": round(20*math.log10(peak),3) if peak>0 else None,
            "rms_dbfs": round(20*math.log10(rms),3) if rms>0 else None,
            "stereo_correlation": round(correlation,5) if correlation is not None else None,
            "mono_compatibility_proxy": round(
                float(np.sqrt(np.mean(((left+right)/2)**2))) / rms, 5
            ) if rms>0 else None,
        })
    summed = np.sum([x[:n] for x in samples], axis=0)
    peak_sum = float(np.max(np.abs(summed)))
    result = {
        "schema_version":"BRStudioStemEvidence/v1",
        "status":"MEASURED", "source_count":len(sources),
        "window_seconds":window_seconds, "rate_hz":RATE,
        "stems":result_stems,
        "unity_sum_sample_peak_dbfs":round(20*math.log10(peak_sum),3) if peak_sum>0 else None,
        "unity_sum_exceeds_0dbfs":bool(peak_sum>1.0),
        "method":"FFmpeg_stereo_f32_16k_original_gain_unity_sum",
        "limitations":"Measured at 16k stereo downmix; unity sum is NOT a REAPER mix, loudness master, phase-corrected render or independent listening verdict",
        "reaper_project_created":False,"quality_approved":False,
    }
    result["evidence_sha256"]=_digest(result)
    return result


def audit_external_word_alignment(path: str | Path) -> dict[str, Any]:
    """Validate locally produced alignment metadata, never run an ASR model.

    The input may contain transcript words; output deliberately contains none.
    Textual matches are not evidence of actual phonemes.
    """
    data = _read_json(path)
    if set(data) != {"language","model_id","audio_sha256","duration_seconds","expected_tokens","aligned_words"}:
        raise ObservationError("STUDIO_ALIGNMENT_SCHEMA_INVALID")
    if data["language"] != "pt" or not isinstance(data["model_id"],str) or not ASSET_ID.fullmatch(data["model_id"]):
        raise ObservationError("STUDIO_ALIGNMENT_MODEL_OR_LANGUAGE_INVALID")
    if not isinstance(data["audio_sha256"],str) or not re.fullmatch(r"[a-f0-9]{64}",data["audio_sha256"]):
        raise ObservationError("STUDIO_ALIGNMENT_SOURCE_HASH_INVALID")
    duration=data["duration_seconds"]
    if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<duration<=3600:
        raise ObservationError("STUDIO_ALIGNMENT_DURATION_INVALID")
    words=data["aligned_words"]
    expected=data["expected_tokens"]
    if not isinstance(words,list) or not isinstance(expected,list) or not 1<=len(words)<=5000 or len(words)!=len(expected):
        raise ObservationError("STUDIO_ALIGNMENT_COUNTS_INVALID")
    counts={"matched_text":0,"lexical_mismatch":0,"unscored":0,"timing_regression":0}
    confidence=[]
    previous=0.0
    for want, item in zip(expected,words):
        if not isinstance(want,str) or len(want)>90 or not isinstance(item,dict) or set(item)!={"word","start","end","score"}:
            raise ObservationError("STUDIO_ALIGNMENT_WORD_SCHEMA_INVALID")
        if not isinstance(item["word"],str) or len(item["word"])>90:
            raise ObservationError("STUDIO_ALIGNMENT_WORD_SCHEMA_INVALID")
        start,end,score=item["start"],item["end"],item["score"]
        if (any(type(x) not in (int,float) or not math.isfinite(x) for x in (start,end,score))
            or not 0<=start<end<=duration+0.01 or not 0<=score<=1):
            raise ObservationError("STUDIO_ALIGNMENT_TIME_OR_SCORE_INVALID")
        if start < previous-0.01:
            counts["timing_regression"]+=1
        previous=max(previous,end)
        def normalized(text:str)->str:
            return "".join(c for c in unicodedata.normalize("NFKD",text.casefold()) if c.isalnum())
        counts["matched_text" if normalized(want)==normalized(item["word"]) else "lexical_mismatch"]+=1
        confidence.append(score)
    receipt={
        "schema_version":"BRPTBRAlignmentEvidence/v1",
        "status":"STRUCTURAL_AND_TEXTUAL_CHECK_ONLY",
        "source_manifest_sha256":_sha256(_source(path)),
        "audio_sha256":data["audio_sha256"],"model_id":data["model_id"],
        "duration_seconds":duration,"word_count":len(words),
        "counts":counts,"mean_alignment_score":round(sum(confidence)/len(confidence),4),
        "phoneme_pronunciation_verified":False,
        "speaker_identity_verified":False,
        "owner_voice_access":"FORBIDDEN",
        "vice_city_pronunciation":"vaicy siti (expected lexicon; NOT acoustically verified)",
        "limits":"WhisperX-style external alignment is not proof that audio actually pronounces the text or matches the sole BR_OWNER_V1 speaker",
    }
    receipt["evidence_sha256"]=_digest(receipt)
    return receipt


def analyze_animation_motion(path: str | Path, *, max_frames: int = 36) -> dict[str, Any]:
    src=_source(path, allowed_suffixes=(".mp4",".mov",".mkv",".webm"))
    if type(max_frames) is not int or not 5<=max_frames<=MAX_VIDEO_FRAMES:
        raise ObservationError("STUDIO_MOTION_FRAME_WINDOW_INVALID")
    probe=probe_media(src)
    stream=next((s for s in probe["streams"] if s["codec_type"]=="video"),None)
    if stream is None:
        raise ObservationError("STUDIO_MOTION_VIDEO_REQUIRED")
    if stream.get("width",0)>1920 or stream.get("height",0)>1080:
        raise ObservationError("STUDIO_MOTION_DIMENSIONS_TOO_LARGE")
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ObservationError("STUDIO_OPENCV_NOT_INSTALLED") from exc
    cap=cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise ObservationError("STUDIO_MOTION_DECODE_UNAVAILABLE")
    try:
        fps=float(cap.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(fps) or not 5<=fps<=120:
            raise ObservationError("STUDIO_MOTION_FPS_UNSUPPORTED")
        metrics=[]
        prev=None
        for i in range(max_frames):
            ok,frame=cap.read()
            if not ok:
                break
            small=cv2.resize(frame,(160,90),interpolation=cv2.INTER_AREA)
            gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
            if prev is not None:
                flow=cv2.calcOpticalFlowFarneback(prev,gray,None,0.5,3,15,3,5,1.2,0)
                global_motion=np.median(flow,axis=(0,1))
                residual=flow-global_motion
                residual_mag=np.sqrt(np.sum(residual*residual,axis=2))
                metrics.append({
                    "camera_translation_proxy_px_160x90":[round(float(v),3) for v in global_motion],
                    "median_relative_motion_px":round(float(np.median(residual_mag)),3),
                    "moving_fraction_over_0_5px":round(float(np.mean(residual_mag>0.5)),4),
                })
            prev=gray
    finally:
        cap.release()
    if len(metrics)<4:
        raise ObservationError("STUDIO_MOTION_INSUFFICIENT_FRAMES")
    mean_motion=sum(x["median_relative_motion_px"] for x in metrics)/len(metrics)
    receipt={
        "schema_version":"BRAnimationMotionEvidence/v1",
        "status":"MEASURED",
        "source_sha256":_sha256(src),
        "frames_analyzed":len(metrics)+1,
        "duration_covered_seconds":round((len(metrics)+1)/fps,3),
        "full_duration_analyzed":probe["duration_seconds"] is not None and (len(metrics)+1)/fps >= probe["duration_seconds"]-0.01,
        "mean_residual_motion_px_160x90":round(mean_motion,3),
        "median_camera_translation_proxy_px_160x90":[round(float(sorted(x["camera_translation_proxy_px_160x90"][k] for x in metrics)[len(metrics)//2]),3) for k in (0,1)],
        "method":"OpenCV_Farneback_160x90_median_flow_proxy",
        "limits":"2D optical-flow proxy is not true 3D camera solve, object tracking, animation style capture or creative judgement",
        "quality_approved":False,
    }
    receipt["evidence_sha256"]=_digest(receipt)
    return receipt


def compile_original_timeline(path: str | Path) -> dict[str, Any]:
    """Compile a bounded original storyboard to genuine OpenTimelineIO JSON.

    No real file paths/media URLs are included; untrusted sources are only
    validated asset identifiers, and no media is rendered or exported.
    """
    data=_read_json(path)
    if set(data)!={"timeline_id","fps_num","fps_den","tracks"}:
        raise ObservationError("STUDIO_TIMELINE_SCHEMA_INVALID")
    if not isinstance(data["timeline_id"],str) or not ASSET_ID.fullmatch(data["timeline_id"]):
        raise ObservationError("STUDIO_TIMELINE_ID_INVALID")
    numerator,denominator=data["fps_num"],data["fps_den"]
    if (type(numerator) is not int or type(denominator) is not int or
        numerator<1 or numerator>120000 or denominator<1 or denominator>1001
        or not 12<=numerator/denominator<=120):
        raise ObservationError("STUDIO_TIMELINE_RATE_INVALID")
    tracks=data["tracks"]
    if not isinstance(tracks,list) or not 1<=len(tracks)<=8:
        raise ObservationError("STUDIO_TIMELINE_TRACK_COUNT_INVALID")
    try:
        import opentimelineio as otio
    except ImportError as exc:
        raise ObservationError("STUDIO_OTIO_NOT_INSTALLED") from exc
    frame_rate=numerator/denominator
    timeline=otio.schema.Timeline(name=data["timeline_id"])
    info=[]
    for t in tracks:
        if not isinstance(t,dict) or set(t)!={"track_id","kind","clips"}:
            raise ObservationError("STUDIO_TIMELINE_TRACK_SCHEMA_INVALID")
        if not isinstance(t["track_id"],str) or not ASSET_ID.fullmatch(t["track_id"]) or t["kind"] not in ("video","audio"):
            raise ObservationError("STUDIO_TIMELINE_TRACK_INVALID")
        clips=t["clips"]
        if not isinstance(clips,list) or not 1<=len(clips)<=120:
            raise ObservationError("STUDIO_TIMELINE_CLIPS_INVALID")
        track=otio.schema.Track(name=t["track_id"],kind=(
            otio.schema.TrackKind.Video if t["kind"]=="video" else otio.schema.TrackKind.Audio))
        cursor=0
        for clip in clips:
            if not isinstance(clip,dict) or set(clip)!={"asset_id","at_frame","source_in_frame","duration_frames"}:
                raise ObservationError("STUDIO_TIMELINE_CLIP_SCHEMA_INVALID")
            asset=clip["asset_id"]
            if not isinstance(asset,str) or not ASSET_ID.fullmatch(asset):
                raise ObservationError("STUDIO_TIMELINE_ASSET_INVALID")
            begin,src_in,dur=(clip[key] for key in ("at_frame","source_in_frame","duration_frames"))
            if (any(type(x) is not int for x in (begin,src_in,dur))
                or begin<cursor or src_in<0 or dur<=0 or begin+dur>3600*frame_rate):
                raise ObservationError("STUDIO_TIMELINE_CLIP_RANGE_INVALID")
            if begin>cursor:
                track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(
                    otio.opentime.RationalTime(0,frame_rate),
                    otio.opentime.RationalTime(begin-cursor,frame_rate))))
            track.append(otio.schema.Clip(
                name=asset,
                media_reference=otio.schema.MissingReference(name="ASSET_ID_ONLY"),
                source_range=otio.opentime.TimeRange(
                    otio.opentime.RationalTime(src_in,frame_rate),
                    otio.opentime.RationalTime(dur,frame_rate)),
                metadata={"br_asset_id":asset},
            ))
            cursor=begin+dur
        timeline.tracks.append(track)
        info.append({"track_id":t["track_id"],"kind":t["kind"],"length_frames":cursor,"clip_count":len(clips)})
    serialized=otio.adapters.write_to_string(timeline,adapter_name="otio_json")
    if len(serialized)>600_000:
        raise ObservationError("STUDIO_TIMELINE_OTIO_TOO_LARGE")
    parsed=otio.adapters.read_from_string(serialized,adapter_name="otio_json")
    if len(parsed.tracks)!=len(tracks):
        raise ObservationError("STUDIO_TIMELINE_ROUNDTRIP_MISMATCH")
    receipt={
        "schema_version":"BROriginalTimelineEvidence/v1",
        "status":"OTIO_SERIALIZED_AND_ROUNDTRIPPED",
        "manifest_sha256":_sha256(_source(path)),"otio_sha256":hashlib.sha256(serialized.encode()).hexdigest(),
        "fps":{"numerator":numerator,"denominator":denominator},
        "tracks":info,"media_resolved":False,"rendered":False,"exported":False,
        "publication_authorized":False,
        "limitations":"Native OTIO timeline structure only. External editor interoperability and media render are NOT proven",
    }
    receipt["evidence_sha256"]=_digest(receipt)
    return receipt
