from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from app.services.google_youtube_publisher_factory import create_google_youtube_publisher
from app.services.media_artifact_locator_service import validate_media_artifact_locator
from app.services.youtube_publisher import YouTubeUploadResult


class YouTubeUploadWorkerError(ValueError):
    pass


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise YouTubeUploadWorkerError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise YouTubeUploadWorkerError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise YouTubeUploadWorkerError(f"{label} must be an object")
    return value


def _safe_child(root: Path, relative_path: str, label: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path.strip():
        raise YouTubeUploadWorkerError(f"missing {label}")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise YouTubeUploadWorkerError(f"unsafe {label}")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise YouTubeUploadWorkerError(f"{label} escapes artifact root")
    return resolved


def _validate_job(job: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(job, dict):
        raise YouTubeUploadWorkerError("upload job must be an object")
    for key in ("publication_id", "video_id", "content_item_id"):
        if isinstance(job.get(key), bool) or not isinstance(job.get(key), int) or job[key] <= 0:
            raise YouTubeUploadWorkerError(f"invalid {key}")
    for key in ("execution_id", "routing_id", "authorization_id"):
        if not isinstance(job.get(key), str) or not job[key].strip():
            raise YouTubeUploadWorkerError(f"missing {key}")
    if job.get("authorized_action") != "YOUTUBE":
        raise YouTubeUploadWorkerError("authorized_action must be YOUTUBE")
    if job.get("capability_id") != "youtube.upload-private":
        raise YouTubeUploadWorkerError("capability_id must be youtube.upload-private")
    if job.get("privacy_status") != "private":
        raise YouTubeUploadWorkerError("cloud worker only accepts private upload")
    if not isinstance(job.get("title"), str) or not job["title"].strip():
        raise YouTubeUploadWorkerError("title is required")
    tags = job.get("tags")
    if not isinstance(tags, list) or not all(isinstance(item, str) for item in tags):
        raise YouTubeUploadWorkerError("tags must be a string list")
    locator = validate_media_artifact_locator(
        job.get("artifact_locator"),
        expected_video_id=job["video_id"],
    )
    result = dict(job)
    result["artifact_locator"] = locator
    return result


def _validate_render_evidence(job: dict[str, Any], artifact_root: Path) -> tuple[Path, dict[str, Any]]:
    locator = job["artifact_locator"]
    media = _safe_child(artifact_root, locator["media_relative_path"], "media_relative_path")
    manifest_path = _safe_child(artifact_root, locator["manifest_relative_path"], "manifest_relative_path")
    probe_path = _safe_child(artifact_root, locator["probe_relative_path"], "probe_relative_path")
    qa_path = _safe_child(artifact_root, locator["qa_relative_path"], "qa_relative_path")
    for path, label in (
        (media, "media"),
        (manifest_path, "render manifest"),
        (probe_path, "video probe"),
        (qa_path, "render QA"),
    ):
        if not path.is_file() or path.stat().st_size <= 0:
            raise YouTubeUploadWorkerError(f"missing or empty {label}")

    manifest = _load_json(manifest_path, "render manifest")
    probe = _load_json(probe_path, "video probe")
    qa = _load_json(qa_path, "render QA")

    expected = {
        "render_job_id": locator["render_job_id"],
        "video_id": job["video_id"],
        "execution_id": locator["execution_id"],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise YouTubeUploadWorkerError(f"render manifest {key} mismatch")
        if qa.get(key) != value:
            raise YouTubeUploadWorkerError(f"render QA {key} mismatch")
        lineage = probe.get("lineage")
        if not isinstance(lineage, dict) or lineage.get(key) != value:
            raise YouTubeUploadWorkerError(f"video probe {key} mismatch")

    if manifest.get("qa_status") != "PASS" or qa.get("status") != "PASS":
        raise YouTubeUploadWorkerError("render QA is not PASS")
    checks = qa.get("checks")
    if not isinstance(checks, dict) or not checks or not all(value is True for value in checks.values()):
        raise YouTubeUploadWorkerError("render QA checks are not all true")

    size = media.stat().st_size
    if manifest.get("size_bytes") != size:
        raise YouTubeUploadWorkerError("render manifest size mismatch")
    with media.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    if manifest.get("sha256") != sha256:
        raise YouTubeUploadWorkerError("render manifest sha256 mismatch")

    streams = probe.get("streams")
    if not isinstance(streams, list):
        raise YouTubeUploadWorkerError("video probe streams missing")
    kinds = {item.get("codec_type") for item in streams if isinstance(item, dict)}
    if not {"video", "audio"}.issubset(kinds):
        raise YouTubeUploadWorkerError("video probe requires video and audio streams")
    try:
        duration = float(probe.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = math.nan
    if not math.isfinite(duration) or duration <= 0:
        raise YouTubeUploadWorkerError("video probe duration invalid")
    manifest_duration = manifest.get("duration_seconds")
    if not isinstance(manifest_duration, (int, float)) or isinstance(manifest_duration, bool):
        raise YouTubeUploadWorkerError("render manifest duration invalid")
    if abs(float(manifest_duration) - duration) > max(0.5, duration * 0.01):
        raise YouTubeUploadWorkerError("render manifest/probe duration mismatch")

    evidence = {
        "render_job_id": locator["render_job_id"],
        "video_id": locator["video_id"],
        "execution_id": locator["execution_id"],
        "workflow_run_id": locator["workflow_run_id"],
        "artifact_id": locator["artifact_id"],
        "media_relative_path": locator["media_relative_path"],
        "size_bytes": size,
        "sha256": sha256,
        "duration_seconds": duration,
        "qa_status": "PASS",
    }
    return media, evidence


def execute(job: dict[str, Any], artifact_root: Path, *, publisher: Any) -> dict[str, Any]:
    job = _validate_job(job)
    media, evidence = _validate_render_evidence(job, artifact_root)
    publication = {
        "id": job["publication_id"],
        "video_id": job["video_id"],
        "content_item_id": job["content_item_id"],
        "title": job["title"].strip(),
        "description": str(job.get("description") or ""),
        "tags": list(job["tags"]),
        "category_id": str(job.get("category_id") or "20"),
        "privacy_status": "private",
        "file_path": str(media),
    }
    result = publisher.upload(publication)
    if not isinstance(result, YouTubeUploadResult):
        raise TypeError("publisher.upload() must return YouTubeUploadResult")
    payload = {
        "publication_id": job["publication_id"],
        "video_id": job["video_id"],
        "content_item_id": job["content_item_id"],
        "authorized_action": "YOUTUBE",
        "capability_id": "youtube.upload-private",
        "routing_id": job["routing_id"],
        "authorization_id": job["authorization_id"],
        "execution_id": job["execution_id"],
        "status": "UPLOADED" if result.success else "FAILED",
        "youtube_video_id": result.youtube_video_id,
        "youtube_url": result.youtube_url,
        "error": result.error,
        "artifact_evidence": evidence,
    }
    if result.success and (not result.youtube_video_id or not result.youtube_url):
        raise YouTubeUploadWorkerError("successful upload result lacks YouTube identity")
    return payload


def main() -> None:
    job_path = Path(os.environ.get("YOUTUBE_UPLOAD_JOB_FILE", "runtime/youtube-upload/upload-job.json"))
    artifact_root = Path(os.environ.get("YOUTUBE_ARTIFACT_ROOT", "runtime/youtube-upload/render-artifact"))
    result_path = Path(os.environ.get("YOUTUBE_UPLOAD_RESULT_FILE", "runtime/youtube-upload/result/youtube-upload-result.json"))
    token_file = os.environ.get("YOUTUBE_TOKEN_FILE")
    secrets_file = os.environ.get("YOUTUBE_CLIENT_SECRETS_FILE")
    if not token_file or not secrets_file:
        raise YouTubeUploadWorkerError("YouTube OAuth credential file paths are required")
    job = _load_json(job_path, "YouTube upload job")
    publisher = create_google_youtube_publisher(
        token_file=token_file,
        client_secrets_file=secrets_file,
    )
    payload = execute(job, artifact_root, publisher=publisher)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if payload["status"] != "UPLOADED":
        raise SystemExit(payload.get("error") or "YouTube private upload failed")


if __name__ == "__main__":
    main()
