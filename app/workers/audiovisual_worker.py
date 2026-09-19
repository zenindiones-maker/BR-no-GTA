"""Execute Harness-authorized EditPlans through the vendored VEdit engine."""
from __future__ import annotations

import argparse
import hashlib
import json
import inspect
import math
import os
import re
import subprocess
import time
from pathlib import Path

from app.services.edit_plan_service import EditPlan
from app.services.render_learning_profile_service import resolve_bound_render_options


class WorkerError(ValueError):
    pass


LINEAGE_FIELDS = (
    "render_job_id",
    "video_id",
    "content_item_id",
    "script_id",
    "idea_id",
    "execution_id",
    "brain_decision_id",
    "authorized_action",
)


def finite(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WorkerError(f"{label}: expected finite number")
    if not math.isfinite(value) or value < minimum:
        raise WorkerError(f"{label}: invalid range")
    return float(value)


def _requires_a1_voice(job: dict) -> bool:
    try:
        duration = float(job.get("estimated_duration_seconds") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return job.get("qa_profile") == "professional-ptbr" or duration >= 300.0


def _validate_a1_voice_contract(job: dict, plan: EditPlan, duration: float) -> None:
    if not _requires_a1_voice(job):
        return
    voice = job.get("a1_voice")
    if not isinstance(voice, dict):
        raise WorkerError("A1 VOICE required for long-form production")
    required = {
        "capability_id": "narration.generate.pt-BR",
        "locale": "pt-BR",
        "qa_status": "PASS",
    }
    for key, expected in required.items():
        if voice.get(key) != expected:
            raise WorkerError(f"A1 VOICE invalid {key}")
    if not isinstance(voice.get("voice"), str) or not voice["voice"].startswith("pt-BR-"):
        raise WorkerError("A1 VOICE must use a PT-BR voice")
    media_path = voice.get("media_path")
    if not isinstance(media_path, str) or not media_path.strip():
        raise WorkerError("A1 VOICE media_path is required")
    digest = voice.get("sha256")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise WorkerError("A1 VOICE sha256 evidence is required")
    voice_duration = finite(voice.get("duration_seconds"), "a1_voice.duration_seconds", .001)
    if abs(voice_duration - duration) > max(0.75, duration * .005):
        raise WorkerError("A1 VOICE/RenderJob duration mismatch")
    a1_tracks = [
        item
        for item in plan.audio
        if item.track.upper() == "A1" and item.media_path == media_path
    ]
    if len(a1_tracks) != 1:
        raise WorkerError("EditPlan must contain exactly one materialized A1 narration track")
    track = a1_tracks[0]
    if track.start_seconds > .001 or track.source_start_seconds > .001:
        raise WorkerError("A1 narration must start at content time zero")
    if track.duration_seconds is None:
        raise WorkerError("A1 narration requires explicit duration")
    if abs(float(track.duration_seconds) - duration) > max(.75, duration * .005):
        raise WorkerError("A1 narration track must cover the complete content timeline")


def validate_job(job, *, allow_runtime_plan=False):
    if not isinstance(job, dict):
        raise WorkerError("RenderJob must be an object")
    reject_secrets(job)
    for key in ("render_job_id", "video_id", "content_item_id", "script_id", "idea_id"):
        if type(job.get(key)) is not int or job[key] <= 0:
            raise WorkerError(f"Missing/invalid {key}; producer: #2/#4")
    for key in ("brain_decision_id", "execution_id"):
        if not isinstance(job.get(key), str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", job[key]
        ):
            raise WorkerError(f"Missing/invalid {key}")
    if job.get("authorized_action") != "EXECUTION":
        raise WorkerError("authorized_action must be EXECUTION")
    for key in ("brain_decision_id", "execution_id", "authorized_action"):
        expected = os.environ.get("EXPECTED_" + key.upper())
        if expected is not None and job[key] != expected:
            raise WorkerError(f"Dispatch envelope mismatch: {key}")
    duration = finite(
        job.get("estimated_duration_seconds"),
        "estimated_duration_seconds",
        .001,
    )
    if not isinstance(job.get("scenes"), list) or not job["scenes"]:
        raise WorkerError("Missing scenes; producer: #2/#4")
    if not all(isinstance(scene, dict) for scene in job["scenes"]):
        raise WorkerError("scenes must contain objects")
    if not isinstance(job.get("edit_plan"), dict):
        if not allow_runtime_plan:
            raise WorkerError("Missing edit_plan; producer: #2/#4")
        if _requires_a1_voice(job):
            raise WorkerError(
                "Long-form production requires persisted EditPlan with materialized A1 VOICE"
            )
        from app.services.render_media_materializer import validate_remote_source

        if not job.get("audio_requirements"):
            raise WorkerError("Runtime EditPlan requires explicit real audio requirements")
        for item in job["scenes"] + job["audio_requirements"]:
            validate_remote_source(item)
        for scene in job["scenes"]:
            for key in ("segment_id", "content_unit_id"):
                if type(scene.get(key)) is not int or scene[key] <= 0:
                    raise WorkerError("Runtime scene missing " + key)
            start = finite(scene.get("source_start_seconds"), "source_start_seconds")
            end = finite(scene.get("source_end_seconds"), "source_end_seconds")
            length = finite(scene.get("duration_seconds"), "duration_seconds", .001)
            if end < start + length:
                raise WorkerError("Invalid scene source window")
        return None
    plan = EditPlan.from_dict(job["edit_plan"])
    finite(plan.duration_seconds, "EditPlan.duration_seconds", .001)
    if abs(plan.duration_seconds - duration) > .001:
        raise WorkerError("EditPlan/RenderJob duration mismatch")
    if (
        plan.content_item_id != job["content_item_id"]
        or plan.script_id != job["script_id"]
    ):
        raise WorkerError("EditPlan/RenderJob lineage mismatch")
    _validate_a1_voice_contract(job, plan, duration)
    return plan


def reject_secrets(value):
    """Fail before archiving credentials accidentally embedded in a job."""
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            credential_key = re.search(
                r"token|password|secret|api[_-]?key",
                key_text,
                re.I,
            )
            authorization_credential = (
                re.search(r"authorization", key_text, re.I)
                and not re.fullmatch(
                    r"(?:[a-z0-9]+_)*authorization_id",
                    key_text,
                    re.I,
                )
            )
            if credential_key or authorization_credential:
                raise WorkerError("Credentials do not belong in RenderJob")
            reject_secrets(child)
    elif isinstance(value, list):
        for child in value:
            reject_secrets(child)
    elif isinstance(value, str) and re.search(
        r"https?://[^\s]*@|-----BEGIN .*PRIVATE KEY|github_pat_|ghp_",
        value,
    ):
        raise WorkerError("Credential-bearing URLs/keys do not belong in RenderJob")


def resolve_asset(media_path, root):
    if not isinstance(media_path, str) or not media_path.strip():
        raise WorkerError(
            "Missing EditPlan media_path; producer: #2/#4; consumer: asset resolver"
        )
    path = Path(media_path)
    if path.is_absolute() or ".." in path.parts:
        raise WorkerError(
            "Cloud media_path must be relative to the provisioned asset root (#2/#4)"
        )
    resolved = (root.resolve() / path).resolve()
    if (
        not resolved.is_relative_to(root.resolve())
        or not resolved.is_file()
        or resolved.stat().st_size == 0
    ):
        raise WorkerError(
            "Missing/unsafe cloud asset; provision artifact using contract #2/#4"
        )
    return resolved


def build_timeline(
    plan,
    asset_root,
    render_config,
    *,
    asset_resolver=resolve_asset,
    a1_voice: dict | None = None,
    require_a1: bool = False,
):
    from vedit.store import Store

    if not isinstance(render_config, dict):
        raise WorkerError("Missing render configuration")
    match = re.fullmatch(
        r"([0-9]+)x([0-9]+)",
        str(render_config.get("resolution", "")),
    )
    if not match:
        raise WorkerError("render.resolution must be WIDTHxHEIGHT")
    width, height = map(int, match.groups())
    if min(width, height) <= 0 or width % 2 or height % 2:
        raise WorkerError("render.resolution must have positive even dimensions")
    fps = finite(render_config.get("fps"), "render.fps", .001)
    if (
        render_config.get("container"),
        render_config.get("video_codec"),
        render_config.get("audio_codec"),
    ) != ("mp4", "h264", "aac"):
        raise WorkerError(
            "Worker supports the existing mp4/h264/aac render configuration"
        )
    store = Store.create(name=plan.title, width=width, height=height, fps=fps)
    track_ids = {}
    segment_clips = {}
    video_windows = []
    has_audio_track = False
    has_a1 = False
    expected_a1_path = (a1_voice or {}).get("media_path")

    def track(name, kind):
        key = (name, kind)
        if key not in track_ids:
            track_ids[key] = store.add_track(kind=kind, name=name).id
        return track_ids[key]

    def add(media_path, track_name, kind, start, source_start, duration):
        nonlocal has_audio_track, has_a1
        finite(start, "clip.start_seconds")
        finite(source_start, "clip.source_start_seconds")
        finite(duration, "clip.duration_seconds", .001)
        if start + duration > plan.duration_seconds + .001:
            raise WorkerError("Clip exceeds EditPlan duration")
        media = store.import_media(
            [str(asset_resolver(media_path, asset_root))]
        )[0]
        if kind == "video":
            if not media.has_video and media.kind != "image":
                raise WorkerError(
                    "Video track references media without video/image content"
                )
            if media.kind == "image" and source_start > .001:
                raise WorkerError("Image source_start_seconds must be zero")
            video_windows.append((start, start + duration))
        if kind == "audio":
            if not media.has_audio:
                raise WorkerError("Audio track references media without audio")
            has_audio_track = True
            if (
                track_name.upper() == "A1"
                and expected_a1_path
                and media_path == expected_a1_path
            ):
                has_a1 = True
        if media.kind != "image":
            if media.duration <= 0:
                raise WorkerError("Source has no measurable duration")
            if source_start + duration > media.duration + .001:
                raise WorkerError(
                    "Source window exceeds media duration; refusing VEdit automatic truncation"
                )
        clip = store.add_clip(
            media.id,
            track_id=track(track_name, kind),
            start=start,
            in_=source_start,
            duration=duration,
        )
        if kind == "video" and hasattr(clip, "audio"):
            # Visual source audio is not A1 VOICE and never satisfies the narration gate.
            clip.audio.mute = True
        return clip

    for item in plan.tracks:
        kind = "video" if item.kind in {"video", "overlay"} else item.kind
        if item.clips and kind not in {"video", "audio"}:
            raise WorkerError("Unsupported clip track kind")
        for source in item.clips:
            clip = add(
                source.media_path,
                item.name,
                kind,
                source.start_seconds,
                source.source_start_seconds,
                source.duration_seconds,
            )
            clip.fit = source.fit
            if source.segment_id is not None:
                if source.segment_id in segment_clips:
                    raise WorkerError("Ambiguous repeated segment_id in EditPlan")
                segment_clips[source.segment_id] = clip

    for source in plan.audio:
        if source.duration_seconds is None:
            raise WorkerError("Audio duration_seconds required for exact execution")
        clip = add(
            source.media_path,
            source.track,
            "audio",
            source.start_seconds,
            source.source_start_seconds,
            source.duration_seconds,
        )
        finite(source.volume, "audio.volume")
        clip.audio.mute = source.volume == 0
        clip.audio.gain_db = (
            20 * math.log10(source.volume) if source.volume else 0
        )
        clip.audio.fade_in = finite(source.fade_in_seconds, "audio.fade_in")
        clip.audio.fade_out = finite(source.fade_out_seconds, "audio.fade_out")

    if not has_audio_track:
        raise WorkerError("No explicit audio track; refusing source-video audio fallback")
    if require_a1 and not has_a1:
        raise WorkerError(
            "A1 VOICE missing from executed timeline; trailer/gameplay audio is not narration"
        )

    covered = 0.0
    for start, end in sorted(video_windows):
        if start > covered + .001:
            raise WorkerError(
                "Video timeline has uncovered gaps; refusing placeholder frames"
            )
        covered = max(covered, end)
    if abs(covered - plan.duration_seconds) > .001:
        raise WorkerError("Video media does not cover the full EditPlan")

    for text in plan.texts:
        finite(text.start_seconds, "text.start")
        finite(text.duration_seconds, "text.duration", .001)
        if (
            text.start_seconds + text.duration_seconds
            > plan.duration_seconds + .001
        ):
            raise WorkerError("Text exceeds EditPlan duration")
        store.add_text(
            text.text,
            track_id=track(text.track, "video"),
            start=text.start_seconds,
            duration=text.duration_seconds,
            font_size=text.font_size,
            color=text.color,
            align=text.align,
            box=text.box,
        )

    for effect in plan.effects:
        if effect.segment_id not in segment_clips:
            raise WorkerError("Effect references missing segment")
        if effect.name.startswith("vedit_graphic:"):
            raise WorkerError(
                "Graphic descriptor reached native VEdit effect boundary"
            )
        store.add_effect(
            segment_clips[effect.segment_id].id,
            effect.name,
            effect.params,
        )

    for transition in plan.transitions:
        a = segment_clips.get(transition.from_segment_id)
        b = segment_clips.get(transition.to_segment_id)
        if a is None or b is None:
            raise WorkerError("Transition references missing segment")
        duration = finite(transition.duration_seconds, "transition.duration")
        transition_type = str(transition.type).strip().lower()
        if transition_type == "cut":
            if duration > .001:
                raise WorkerError("CUT transition must have zero duration")
            continue
        if duration and (
            abs(a.end - b.start - duration) > .001
            or duration > min(a.duration, b.duration)
        ):
            raise WorkerError(
                "Transition requires explicit overlapping clips; worker cannot retime editorial plan"
            )
        store.set_transition(a.id, type=transition_type, duration=duration)
    return store.project


def probe_video(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode or result.stderr.strip():
        raise WorkerError("ffprobe failed")
    return json.loads(result.stdout)


def evaluate_probe(probe, expected, qa):
    try:
        raw_duration = probe.get("format", {}).get("duration")
        duration = (
            float(raw_duration)
            if not isinstance(raw_duration, bool)
            else math.nan
        )
    except (TypeError, ValueError):
        duration = math.nan
    kinds = {s.get("codec_type") for s in probe.get("streams", [])}
    formats = probe.get("format", {}).get("format_name", "").split(",")
    checks = {
        "mp4_container": "mp4" in formats,
        "video_stream": "video" in kinds,
        "audio_stream": "audio" in kinds,
        "finite_positive_duration": math.isfinite(duration) and duration > 0,
        "expected_duration": math.isfinite(duration)
        and abs(duration - expected) <= max(.5, expected * .01),
        "plan_min_duration": qa.min_duration_seconds is None
        or duration >= qa.min_duration_seconds,
        "plan_max_duration": qa.max_duration_seconds is None
        or duration <= qa.max_duration_seconds,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "duration_seconds": duration if math.isfinite(duration) else None,
    }


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )


def execute(job, asset_root, output_root, *, source_job=None):
    plan = validate_job(job)
    folder = (
        output_root
        / job["execution_id"]
        / str(job["render_job_id"])
    )
    folder.mkdir(parents=True, exist_ok=False)
    output = folder / f"{job['video_id']}.mp4"
    qa = {"status": "FAIL", "stage": "timeline"}
    try:
        write_json(
            folder / "render-job.json",
            source_job if source_job is not None else job,
        )
        write_json(folder / "edit-plan.json", job["edit_plan"])
        project = build_timeline(
            plan,
            asset_root,
            job.get("render"),
            a1_voice=job.get("a1_voice"),
            require_a1=_requires_a1_voice(job),
        )
        from vedit.render import RenderOptions, render

        qa["stage"] = "render"
        bound_options = resolve_bound_render_options(job.get("render"))
        learning_binding = dict((job.get("render") or {}).get("learning_profile") or {})
        progress_path = folder / "render-progress.json"
        heartbeat = {"last_emit": 0.0}

        def _record_progress(progress):
            payload = dict(progress or {})
            payload.update({
                "status": "RUNNING",
                "render_job_id": job["render_job_id"],
                "video_id": job["video_id"],
                "execution_id": job["execution_id"],
                "skill_id": learning_binding.get("skill_id"),
                "skill_version": learning_binding.get("version", "v1-legacy"),
                "encoder_policy": {
                    "codec": bound_options["codec"],
                    "quality": bound_options["quality"],
                    "software_preset": bound_options.get("software_preset"),
                    "timeline_placement": bound_options.get("timeline_placement", "legacy_tpad"),
                    "compact_text_overlays": bool(bound_options.get("compact_text_overlays", False)),
                    "prefer_hw": bound_options["prefer_hw"],
                    "hwaccel_decode": bound_options["hwaccel_decode"],
                    "threads": render_threads,
                },
            })
            write_json(progress_path, payload)
            now = time.monotonic()
            percent = float(payload.get("percent") or 0.0)
            if (
                heartbeat["last_emit"] == 0.0
                or now - heartbeat["last_emit"] >= 30.0
                or percent >= 100.0
            ):
                heartbeat["last_emit"] = now
                elapsed = float(payload.get("elapsed") or 0.0)
                media_seconds = float(payload.get("seconds") or 0.0)
                speed_x = media_seconds / elapsed if elapsed > 0 else None
                print(
                    json.dumps(
                        {
                            "RENDER_HEARTBEAT": "PASS",
                            "render_job_id": job["render_job_id"],
                            "execution_id": job["execution_id"],
                            "skill_version": learning_binding.get("version", "v1-legacy"),
                            "software_preset": bound_options.get("software_preset"),
                            "percent": percent,
                            "media_seconds": media_seconds,
                            "elapsed_seconds": elapsed,
                            "render_speed_x": (
                                round(speed_x, 6) if speed_x is not None else None
                            ),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )

        threads_raw = (os.environ.get("VEDIT_RENDER_THREADS") or "").strip()
        render_threads = None
        if threads_raw:
            try:
                render_threads = int(threads_raw)
            except ValueError as exc:
                raise WorkerError("VEDIT_RENDER_THREADS must be an integer") from exc
            if render_threads <= 0 or render_threads > 256:
                raise WorkerError("VEDIT_RENDER_THREADS is outside safe bounds")
        render_options = RenderOptions(
            output=str(output),
            codec=bound_options["codec"],
            quality=bound_options["quality"],
            prefer_hw=bound_options["prefer_hw"],
            hwaccel_decode=bound_options["hwaccel_decode"],
            software_preset=bound_options.get("software_preset"),
            timeline_placement=bound_options.get("timeline_placement", "legacy_tpad"),
            compact_text_overlays=bool(bound_options.get("compact_text_overlays", False)),
            threads=render_threads,
        )
        render_parameters = inspect.signature(render).parameters
        if "on_progress" in render_parameters:
            render_result = render(
                project,
                render_options,
                on_progress=_record_progress,
            )
        else:
            # Preserve compatibility with injected legacy render adapters while
            # the real VEdit binding receives progress telemetry.
            render_result = render(project, render_options)
        if render_result is None:
            if learning_binding:
                raise WorkerError(
                    "Harness-bound VEdit render returned no runtime evidence"
                )
            # Legacy/injected adapters used by compatibility tests predate the
            # RenderResult telemetry contract. They may still prove the older
            # worker gates, but can never satisfy a learning-bound execution.
            runtime_metrics = None
        else:
            runtime_metrics = {
                "status": "COMPLETED",
                "wall_clock_seconds": render_result.seconds,
                "media_duration_seconds": render_result.duration,
                "realtime_factor": (
                    round(render_result.seconds / render_result.duration, 6)
                    if render_result.duration > 0 else None
                ),
                "render_speed_x": (
                    round(render_result.duration / render_result.seconds, 6)
                    if render_result.seconds > 0 else None
                ),
                "encoder": render_result.encoder,
                "size_bytes": render_result.size,
                "warnings": list(render_result.warnings),
                "stage_timings": dict(getattr(render_result, "stage_timings", {}) or {}),
                "resource_usage": dict(getattr(render_result, "resource_usage", {}) or {}),
                "skill_id": learning_binding.get("skill_id"),
                "skill_version": learning_binding.get("version", "v1-legacy"),
                "content_ref": learning_binding.get("content_ref"),
                "checksum": learning_binding.get("checksum"),
                "encoder_policy": {
                    "codec": bound_options["codec"],
                    "quality": bound_options["quality"],
                    "software_preset": bound_options.get("software_preset"),
                    "timeline_placement": bound_options.get("timeline_placement", "legacy_tpad"),
                    "compact_text_overlays": bool(bound_options.get("compact_text_overlays", False)),
                    "prefer_hw": bound_options["prefer_hw"],
                    "hwaccel_decode": bound_options["hwaccel_decode"],
                },
            }
            write_json(folder / "render-runtime.json", runtime_metrics)
            write_json(progress_path, runtime_metrics)
            qa["render_runtime"] = runtime_metrics
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
        qa["checks"]["a1_voice_contract"] = not _requires_a1_voice(job) or (
            isinstance(job.get("a1_voice"), dict)
            and job["a1_voice"].get("qa_status") == "PASS"
        )
        if qa["status"] != "PASS" or not all(qa["checks"].values()):
            qa["status"] = "FAIL"
            raise WorkerError("Audiovisual QA failed")
        qa["stage"] = "decode"
        qa["checks"]["full_decode"] = False
        decode = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(output),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=3600,
        )
        if decode.returncode or decode.stderr.strip():
            qa["status"] = "FAIL"
            raise WorkerError("Full decode QA failed")
        qa["checks"]["full_decode"] = True
        qa["stage"] = "complete"
        qa["status"] = "PASS"
        manifest = {key: job[key] for key in LINEAGE_FIELDS}
        manifest.update(
            filename=output.name,
            size_bytes=output.stat().st_size,
            duration_seconds=qa["duration_seconds"],
            qa_status="PASS",
            qa_profile=job.get("qa_profile"),
            a1_voice_sha256=(job.get("a1_voice") or {}).get("sha256"),
        )
        with output.open("rb") as stream:
            manifest["sha256"] = hashlib.file_digest(
                stream,
                "sha256",
            ).hexdigest()
        write_json(folder / "render-manifest.json", manifest)
        return folder
    except Exception:
        qa["status"] = "FAIL"
        raise
    finally:
        qa.update({key: job[key] for key in LINEAGE_FIELDS})
        write_json(folder / "render-qa.json", qa)


def _runtime_relative(value: str, root: Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        candidate = (root / path).resolve()
        if candidate.is_relative_to(root.resolve()) and candidate.exists():
            return str(candidate.relative_to(root.resolve()))
        return value
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise WorkerError("Runtime asset escaped materialization root")
    return str(resolved.relative_to(root.resolve()))


def execute_cloud(job, asset_root, output_root):
    validate_job(job, allow_runtime_plan=True)
    remote = any(scene.get("asset_ref") for scene in job["scenes"])
    if not remote:
        return execute(job, asset_root, output_root)

    from copy import deepcopy
    from app.services.render_media_materializer import materialize_scenes
    from app.services.vedit_service import create_edit_plan

    root = (
        asset_root
        / job["execution_id"]
        / str(job["render_job_id"])
    )
    diagnostic = (
        output_root.parent
        / "materialization"
        / job["execution_id"]
        / str(job["render_job_id"])
    )
    diagnostic.mkdir(parents=True, exist_ok=True)
    write_json(diagnostic / "render-job.json", job)
    qa = {"status": "FAIL", "stage": "materialization"}
    try:
        hydrated, evidence = materialize_scenes(job, root)
        write_json(diagnostic / "assets.json", evidence)
        effective = deepcopy(job)
        if not isinstance(job.get("edit_plan"), dict):
            qa["stage"] = "edit_plan"
            effective["edit_plan"] = create_edit_plan(
                production_plan=hydrated,
                brain_decision=job,
            ).to_dict()

        paths = {
            scene["asset_ref"]: scene["media_path"]
            for scene in hydrated["scenes"]
            + hydrated.get("audio_requirements", [])
        }
        for scene in hydrated["scenes"]:
            paths[str(scene.get("segment_id"))] = scene["media_path"]

        for track in effective["edit_plan"]["tracks"]:
            for clip in track.get("clips", []):
                raw = clip["media_path"]
                mapped = paths.get(
                    raw,
                    paths.get(str(clip.get("segment_id")), raw),
                )
                if mapped != raw:
                    clip["media_path"] = _runtime_relative(mapped, root)
                else:
                    clip["media_path"] = _runtime_relative(raw, root)

        for audio in effective["edit_plan"].get("audio", []):
            raw = audio["media_path"]
            mapped = paths.get(raw, raw)
            audio["media_path"] = _runtime_relative(mapped, root)

        voice = effective.get("a1_voice")
        if isinstance(voice, dict):
            voice["media_path"] = _runtime_relative(
                voice["media_path"],
                root,
            )
            effective["a1_voice"] = voice

        qa["stage"] = "render"
        folder = execute(
            effective,
            root,
            output_root,
            source_job=job,
        )
        write_json(folder / "assets.json", evidence)
        qa = {
            "status": "PASS",
            "stage": "complete",
            "asset_count": len(evidence),
            "a1_voice": (
                effective.get("a1_voice") or {}
            ).get("qa_status"),
        }
        return folder
    finally:
        write_json(diagnostic / "materialization-qa.json", qa)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--render-job", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        job = json.loads(
            args.render_job.read_text(encoding="utf-8")
        )
        folder = execute_cloud(
            job,
            args.asset_root,
            args.output_dir,
        )
    except Exception as exc:
        raise SystemExit(str(exc)) from None
    print(f"RENDER_OUTPUT_DIR={folder}")
    print("AUDIOVISUAL_WORKER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
