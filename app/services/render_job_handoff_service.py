from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.services.audiovisual_render_request_service import build_worker_safe_render_job


class RenderJobHandoffError(ValueError):
    pass


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DESCRIPTOR_SCHEMA = "render-job-handoff/v1"
_FORBIDDEN_FINAL_RENDER_JOBS = {18, 20}


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_artifact_descriptor(
    *,
    render_job_path: Path,
    job: dict[str, Any],
    artifact_id: int,
    artifact_name: str,
    producer_run_id: int,
    producer_workflow: str,
    source_sha: str,
) -> dict[str, Any]:
    if not render_job_path.is_file():
        raise RenderJobHandoffError("render-job.json does not exist")
    descriptor = {
        "schema": _DESCRIPTOR_SCHEMA,
        "transport_mode": "artifact",
        "render_job_id": job.get("render_job_id"),
        "video_id": job.get("video_id"),
        "execution_id": job.get("execution_id"),
        "goal_id": job.get("goal_id"),
        "brain_decision_id": job.get("brain_decision_id"),
        "authorized_action": job.get("authorized_action"),
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "producer_run_id": producer_run_id,
        "producer_workflow": producer_workflow,
        "source_sha": source_sha,
        "render_job_sha256": sha256_file(render_job_path),
    }
    _validate_descriptor_shape(descriptor)
    _validate_job_against_descriptor(job, descriptor)
    return descriptor


def validate_artifact_descriptor(descriptor: dict[str, Any]) -> None:
    _validate_descriptor_shape(descriptor)


def _validate_descriptor_shape(descriptor: dict[str, Any]) -> None:
    if descriptor.get("schema") != _DESCRIPTOR_SCHEMA:
        raise RenderJobHandoffError("unsupported RenderJob handoff schema")
    if descriptor.get("transport_mode") != "artifact":
        raise RenderJobHandoffError("artifact descriptor transport_mode mismatch")
    for key in ("render_job_id", "video_id", "artifact_id", "producer_run_id"):
        value = descriptor.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise RenderJobHandoffError(f"descriptor {key} must be a positive integer")
    if descriptor["render_job_id"] in _FORBIDDEN_FINAL_RENDER_JOBS:
        raise RenderJobHandoffError("Job18 is frozen and Job20 cannot become a final product")
    for key in (
        "execution_id",
        "goal_id",
        "brain_decision_id",
        "authorized_action",
        "artifact_name",
        "producer_workflow",
    ):
        value = descriptor.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RenderJobHandoffError(f"descriptor {key} is required")
    if descriptor.get("authorized_action") != "EXECUTION":
        raise RenderJobHandoffError("artifact handoff requires EXECUTION authorization")
    digest = descriptor.get("render_job_sha256")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise RenderJobHandoffError("descriptor render_job_sha256 is invalid")
    source_sha = descriptor.get("source_sha")
    if not isinstance(source_sha, str) or not _GIT_SHA_RE.fullmatch(source_sha):
        raise RenderJobHandoffError("descriptor source_sha is invalid")


def _validate_job_against_descriptor(job: dict[str, Any], descriptor: dict[str, Any]) -> None:
    try:
        worker_safe = build_worker_safe_render_job(job)
    except ValueError as exc:
        raise RenderJobHandoffError(str(exc)) from exc
    if worker_safe != job:
        raise RenderJobHandoffError(
            "artifact-backed RenderJob contains governance-only authorization metadata"
        )
    required_job_keys = (
        "render_job_id",
        "video_id",
        "execution_id",
        "goal_id",
        "brain_decision_id",
        "authorized_action",
    )
    missing = [key for key in required_job_keys if key not in job]
    if missing:
        raise RenderJobHandoffError("RenderJob schema missing: " + ",".join(missing))
    for key in required_job_keys:
        if job.get(key) != descriptor.get(key):
            raise RenderJobHandoffError(f"RenderJob handoff identity mismatch: {key}")
    if job.get("issued_by") != "deepseek_harness":
        raise RenderJobHandoffError("artifact-backed RenderJob must be issued by deepseek_harness")
    if job.get("render_job_id") in _FORBIDDEN_FINAL_RENDER_JOBS:
        raise RenderJobHandoffError("Job18 is frozen and Job20 cannot become a final product")
    if job.get("youtube_publication") is True:
        raise RenderJobHandoffError("YouTube publication is forbidden in RUN-001 review transport")


def resolve_render_job(
    *,
    inline_json: str | None,
    descriptor_json: str | None,
    artifact_root: Path | None,
    expected_brain_decision_id: str,
    expected_execution_id: str,
    expected_authorized_action: str,
    expected_source_sha: str | None = None,
) -> tuple[dict[str, Any], str]:
    inline_json = (inline_json or "").strip()
    descriptor_json = (descriptor_json or "").strip()
    if bool(inline_json) == bool(descriptor_json):
        raise RenderJobHandoffError("exactly one RenderJob transport must be supplied")

    if inline_json:
        try:
            job = json.loads(inline_json)
        except json.JSONDecodeError as exc:
            raise RenderJobHandoffError("inline RenderJob is not valid JSON") from exc
        if not isinstance(job, dict):
            raise RenderJobHandoffError("inline RenderJob must be an object")
        mode = "inline"
    else:
        try:
            descriptor = json.loads(descriptor_json)
        except json.JSONDecodeError as exc:
            raise RenderJobHandoffError("RenderJob descriptor is not valid JSON") from exc
        if not isinstance(descriptor, dict):
            raise RenderJobHandoffError("RenderJob descriptor must be an object")
        _validate_descriptor_shape(descriptor)
        if expected_source_sha is not None and descriptor.get("source_sha") != expected_source_sha:
            raise RenderJobHandoffError("RenderJob handoff source commit mismatch")
        if artifact_root is None:
            raise RenderJobHandoffError("artifact root is required for artifact-backed RenderJob")
        render_job_path = artifact_root / "render-job.json"
        if not artifact_root.exists():
            raise RenderJobHandoffError("RenderJob handoff artifact does not exist")
        if not render_job_path.is_file():
            raise RenderJobHandoffError("RenderJob handoff artifact is missing render-job.json")
        actual_digest = sha256_file(render_job_path)
        if actual_digest != descriptor.get("render_job_sha256"):
            raise RenderJobHandoffError("RenderJob handoff SHA-256 mismatch")
        try:
            job = json.loads(render_job_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RenderJobHandoffError("artifact render-job.json is not valid JSON") from exc
        if not isinstance(job, dict):
            raise RenderJobHandoffError("artifact render-job.json must be an object")
        _validate_job_against_descriptor(job, descriptor)
        mode = "artifact"

    if job.get("render_job_id") in _FORBIDDEN_FINAL_RENDER_JOBS:
        raise RenderJobHandoffError("Job18 is frozen and Job20 cannot become a final product")
    if job.get("youtube_publication") is True:
        raise RenderJobHandoffError("YouTube publication is forbidden in RUN-001 review transport")
    for key, expected in (
        ("brain_decision_id", expected_brain_decision_id),
        ("execution_id", expected_execution_id),
        ("authorized_action", expected_authorized_action),
    ):
        if job.get(key) != expected:
            raise RenderJobHandoffError(f"Dispatch envelope mismatch: {key}")
    return job, mode
