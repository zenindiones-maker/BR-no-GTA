"""Execute the existing EditPlan through the vendored VEdit engine.

Only resolves already provisioned relative media paths. Remote artifact references
must be supplied by the application contract (#2/#4), not guessed by this worker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path

from app.services.edit_plan_service import EditPlan


class WorkerError(ValueError):
    pass


LINEAGE_FIELDS = (
    "render_job_id", "video_id", "content_item_id", "script_id", "idea_id",
    "execution_id", "brain_decision_id", "authorized_action",
)


def finite(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkerError(f"{label}: expected finite number")
    if not math.isfinite(value) or value < minimum:
        raise WorkerError(f"{label}: invalid range")
    return float(value)


def validate_job(job):
    if not isinstance(job, dict):
        raise WorkerError("RenderJob must be an object")
    reject_secrets(job)
    for key in ("render_job_id", "video_id", "content_item_id", "script_id", "idea_id"):
        if type(job.get(key)) is not int or job[key] <= 0:
            raise WorkerError(f"Missing/invalid {key}; producer: #2/#4")
    for key in ("brain_decision_id", "execution_id"):
        if not isinstance(job.get(key), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job[key]):
            raise WorkerError(f"Missing/invalid {key}")
    if job.get("authorized_action") != "EXECUTION":
        raise WorkerError("authorized_action must be EXECUTION")
    for key in ("brain_decision_id", "execution_id", "authorized_action"):
        expected = os.environ.get("EXPECTED_" + key.upper())
        if expected is not None and job[key] != expected:
            raise WorkerError(f"Dispatch envelope mismatch: {key}")
    duration = finite(job.get("estimated_duration_seconds"), "estimated_duration_seconds", .001)
    if not isinstance(job.get("scenes"), list) or not job["scenes"]:
        raise WorkerError("Missing scenes; producer: #2/#4")
    if not all(isinstance(scene, dict) for scene in job["scenes"]):
        raise WorkerError("scenes must contain objects")
    if not isinstance(job.get("edit_plan"), dict):
        raise WorkerError("Missing edit_plan; producer: #2/#4")
    plan = EditPlan.from_dict(job["edit_plan"])
    finite(plan.duration_seconds, "EditPlan.duration_seconds", .001)
    if abs(plan.duration_seconds - duration) > .001:
        raise WorkerError("EditPlan/RenderJob duration mismatch")
    if plan.content_item_id != job["content_item_id"] or plan.script_id != job["script_id"]:
        raise WorkerError("EditPlan/RenderJob lineage mismatch")
    return plan


def reject_secrets(value):
    """Fail before archiving credentials accidentally embedded in a job."""
    if isinstance(value, dict):
        for key, child in value.items():
            if re.search(r"token|password|secret|api[_-]?key|authorization", str(key), re.I):
                raise WorkerError("Credentials do not belong in RenderJob")
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)
    elif isinstance(value, str) and re.search(r"https?://[^\s]*[?@]|-----BEGIN .*PRIVATE KEY|github_pat_|ghp_", value):
        raise WorkerError("Credential-bearing URLs/keys do not belong in RenderJob")


def resolve_asset(media_path, root):
    if not isinstance(media_path, str) or not media_path.strip():
        raise WorkerError("Missing EditPlan media_path; producer: #2/#4; consumer: asset resolver")
    path = Path(media_path)
    if path.is_absolute() or ".." in path.parts:
        raise WorkerError("Cloud media_path must be relative to the provisioned asset root (#2/#4)")
    resolved = (root.resolve() / path).resolve()
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file() or resolved.stat().st_size == 0:
        raise WorkerError("Missing/unsafe cloud asset; provision artifact using contract #2/#4")
    return resolved


def build_timeline(plan, asset_root, render_config, *, asset_resolver=resolve_asset):
    from vedit.store import Store

    if not isinstance(render_config, dict):
        raise WorkerError("Missing render configuration")
    match = re.fullmatch(r"([0-9]+)x([0-9]+)", str(render_config.get("resolution", "")))
    if not match:
        raise WorkerError("render.resolution must be WIDTHxHEIGHT")
    width, height = map(int, match.groups())
    if min(width, height) <= 0 or width % 2 or height % 2:
        raise WorkerError("render.resolution must have positive even dimensions")
    fps = finite(render_config.get("fps"), "render.fps", .001)
    if (render_config.get("container"), render_config.get("video_codec"), render_config.get("audio_codec")) != ("mp4", "h264", "aac"):
        raise WorkerError("Worker supports the existing mp4/h264/aac render configuration")
    store = Store.create(name=plan.title, width=width, height=height, fps=fps)
    track_ids = {}
    segment_clips = {}
    has_audio = False
    video_windows = []

    def track(name, kind):
        key = (name, kind)
        if key not in track_ids:
            track_ids[key] = store.add_track(kind=kind, name=name).id
        return track_ids[key]

    def add(media_path, track_name, kind, start, source_start, duration):
        nonlocal has_audio
        finite(start, "clip.start_seconds")
        finite(source_start, "clip.source_start_seconds")
        finite(duration, "clip.duration_seconds", .001)
        if start + duration > plan.duration_seconds + .001:
            raise WorkerError("Clip exceeds EditPlan duration")
        media = store.import_media([str(asset_resolver(media_path, asset_root))])[0]
        if kind == "video":
            if not media.has_video:
                raise WorkerError("Video track references media without video")
            video_windows.append((start, start + duration))
        if kind == "audio" and not media.has_audio:
            raise WorkerError("Audio track references media without audio")
        if media.duration > 0 and source_start + duration > media.duration + .001:
            raise WorkerError("Source window exceeds media duration; refusing VEdit automatic truncation")
        if media.kind != "image" and media.duration <= 0:
            raise WorkerError("Source has no measurable duration")
        clip = store.add_clip(media.id, track_id=track(track_name, kind), start=start, in_=source_start, duration=duration)
        has_audio = has_audio or bool(media.has_audio)
        return clip

    for item in plan.tracks:
        kind = "video" if item.kind in {"video", "overlay"} else item.kind
        if item.clips and kind not in {"video", "audio"}:
            raise WorkerError("Unsupported clip track kind")
        for source in item.clips:
            clip = add(source.media_path, item.name, kind, source.start_seconds, source.source_start_seconds, source.duration_seconds)
            clip.fit = source.fit
            if source.segment_id is not None:
                if source.segment_id in segment_clips:
                    raise WorkerError("Ambiguous repeated segment_id in EditPlan")
                segment_clips[source.segment_id] = clip
    for source in plan.audio:
        if source.duration_seconds is None:
            raise WorkerError("Audio duration_seconds required for exact execution")
        clip = add(source.media_path, source.track, "audio", source.start_seconds, source.source_start_seconds, source.duration_seconds)
        finite(source.volume, "audio.volume")
        clip.audio.mute = source.volume == 0
        clip.audio.gain_db = 20 * math.log10(source.volume) if source.volume else 0
        clip.audio.fade_in = finite(source.fade_in_seconds, "audio.fade_in")
        clip.audio.fade_out = finite(source.fade_out_seconds, "audio.fade_out")
    if not has_audio:
        raise WorkerError("No real source audio; refusing synthetic silence")
    covered = 0.0
    for start, end in sorted(video_windows):
        if start > covered + .001:
            raise WorkerError("Video timeline has uncovered gaps; refusing placeholder frames")
        covered = max(covered, end)
    if abs(covered - plan.duration_seconds) > .001:
        raise WorkerError("Video media does not cover the full EditPlan")
    for text in plan.texts:
        finite(text.start_seconds, "text.start")
        finite(text.duration_seconds, "text.duration", .001)
        if text.start_seconds + text.duration_seconds > plan.duration_seconds + .001:
            raise WorkerError("Text exceeds EditPlan duration")
        store.add_text(text.text, track_id=track(text.track, "video"), start=text.start_seconds, duration=text.duration_seconds, font_size=text.font_size, color=text.color, align=text.align, box=text.box)
    for effect in plan.effects:
        if effect.segment_id not in segment_clips:
            raise WorkerError("Effect references missing segment")
        store.add_effect(segment_clips[effect.segment_id].id, effect.name, effect.params)
    for transition in plan.transitions:
        a = segment_clips.get(transition.from_segment_id)
        b = segment_clips.get(transition.to_segment_id)
        if a is None or b is None:
            raise WorkerError("Transition references missing segment")
        duration = finite(transition.duration_seconds, "transition.duration")
        if duration and (abs(a.end - b.start - duration) > .001 or duration > min(a.duration, b.duration)):
            raise WorkerError("Transition requires explicit overlapping clips; worker cannot retime editorial plan")
        store.set_transition(a.id, type=transition.type, duration=duration)
    return store.project


def probe_video(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, timeout=120)
    if result.returncode or result.stderr.strip():
        raise WorkerError("ffprobe failed")
    return json.loads(result.stdout)


def evaluate_probe(probe, expected, qa):
    try:
        raw_duration = probe.get("format", {}).get("duration")
        duration = float(raw_duration) if not isinstance(raw_duration, bool) else math.nan
    except (TypeError, ValueError):
        duration = math.nan
    kinds = {s.get("codec_type") for s in probe.get("streams", [])}
    formats = probe.get("format", {}).get("format_name", "").split(",")
    checks = {
        "mp4_container": "mp4" in formats,
        "video_stream": "video" in kinds,
        "audio_stream": "audio" in kinds,
        "finite_positive_duration": math.isfinite(duration) and duration > 0,
        "expected_duration": math.isfinite(duration) and abs(duration - expected) <= max(.5, expected * .01),
        "plan_min_duration": qa.min_duration_seconds is None or duration >= qa.min_duration_seconds,
        "plan_max_duration": qa.max_duration_seconds is None or duration <= qa.max_duration_seconds,
    }
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "duration_seconds": duration if math.isfinite(duration) else None}


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def execute(job, asset_root, output_root):
    plan = validate_job(job)
    folder = output_root / job["execution_id"] / str(job["render_job_id"])
    folder.mkdir(parents=True, exist_ok=False)
    output = folder / f"{job['video_id']}.mp4"
    qa = {"status": "FAIL", "stage": "timeline"}
    try:
        # Preserve the validated input unchanged before any operation can fail.
        write_json(folder / "render-job.json", job)
        project = build_timeline(plan, asset_root, job.get("render"))
        from vedit.render import RenderOptions, render
        qa["stage"] = "render"
        render(project, RenderOptions(output=str(output), prefer_hw=False, hwaccel_decode=False))
        if not output.is_file() or output.stat().st_size <= 0:
            raise WorkerError("Missing or empty output")
        if len(list(folder.glob("*.mp4"))) != 1:
            raise WorkerError("Expected exactly one final MP4")
        qa["stage"] = "probe"
        probe = probe_video(output)
        probe["lineage"] = {key: job[key] for key in LINEAGE_FIELDS}
        write_json(folder / "video-probe.json", probe)
        qa = evaluate_probe(probe, plan.duration_seconds, plan.qa)
        qa["stage"] = "probe"
        qa["checks"]["nonempty_file"] = True
        qa["checks"]["exactly_one_mp4"] = True
        if qa["status"] != "PASS":
            raise WorkerError("Audiovisual QA failed")
        qa["stage"] = "decode"
        qa["checks"]["full_decode"] = False
        decode = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(output), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], capture_output=True, timeout=3600)
        if decode.returncode or decode.stderr.strip():
            qa["status"] = "FAIL"
            raise WorkerError("Full decode QA failed")
        qa["checks"]["full_decode"] = True
        qa["stage"] = "complete"
        manifest = {key: job[key] for key in LINEAGE_FIELDS}
        manifest.update(filename=output.name, size_bytes=output.stat().st_size, duration_seconds=qa["duration_seconds"], qa_status="PASS")
        with output.open("rb") as stream:
            manifest["sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        write_json(folder / "render-manifest.json", manifest)
        return folder
    except Exception:
        qa["status"] = "FAIL"
        raise
    finally:
        qa.update({key: job[key] for key in LINEAGE_FIELDS})
        write_json(folder / "render-qa.json", qa)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-job", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        job = json.loads(args.render_job.read_text(encoding="utf-8"))
        folder = execute(job, args.asset_root, args.output_dir)
    except Exception as exc:
        # Never expose raw job contents, signed URLs or FFmpeg command logs.
        detail = str(exc) if isinstance(exc, WorkerError) else "inspect contract and QA evidence"
        print(f"Audiovisual worker FAIL ({type(exc).__name__}): {detail}")
        raise SystemExit(1) from None
    print(f"Audiovisual QA PASS: {folder}")


if __name__ == "__main__":
    main()
