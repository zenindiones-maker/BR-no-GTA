from __future__ import annotations

from typing import Any
from urllib.parse import quote


LOCATOR_VERSION = 1


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _safe_token(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    token = value.strip()
    if token in {".", ".."} or "/" in token or "\\" in token:
        raise ValueError(f"{label} must be a single safe path token")
    return token


def build_github_media_artifact_locator(
    render_job: dict[str, Any],
    github_execution: dict[str, Any],
) -> dict[str, Any]:
    """Build the canonical durable locator for one rendered MP4.

    The locator is control-plane metadata only.  It identifies the exact media
    and evidence files inside the already persisted GitHub Actions artifact; it
    never downloads media and it does not create a second storage system.
    """
    if not isinstance(render_job, dict):
        raise ValueError("render_job must be an object")
    if not isinstance(github_execution, dict):
        raise ValueError("github_execution must be an object")

    render_job_id = _positive_int(
        render_job.get("render_job_id") or render_job.get("id"),
        "render_job_id",
    )
    video_id = _positive_int(render_job.get("video_id"), "video_id")
    execution_id = _safe_token(render_job.get("execution_id"), "execution_id")

    run_id = _positive_int(github_execution.get("run_id"), "workflow_run_id")
    artifact_id = _positive_int(github_execution.get("artifact_id"), "artifact_id")
    artifact_size = _positive_int(
        github_execution.get("artifact_size_in_bytes"),
        "artifact_size_in_bytes",
    )
    repository = github_execution.get("repository")
    workflow = github_execution.get("workflow")
    artifact_name = github_execution.get("artifact_name")
    if not isinstance(repository, str) or repository.count("/") != 1:
        raise ValueError("repository must be owner/name")
    workflow = _safe_token(workflow, "workflow")
    artifact_name = _safe_token(artifact_name, "artifact_name")
    if github_execution.get("artifact_expired") is not False:
        raise ValueError("artifact must be present and non-expired")

    base = f"{execution_id}/{render_job_id}"
    media_relative_path = f"{base}/{video_id}.mp4"
    manifest_relative_path = f"{base}/render-manifest.json"
    probe_relative_path = f"{base}/video-probe.json"
    qa_relative_path = f"{base}/render-qa.json"
    render_job_relative_path = f"{base}/render-job.json"
    edit_plan_relative_path = f"{base}/edit-plan.json"

    artifact_uri = github_execution.get("artifact_remote_uri")
    if not isinstance(artifact_uri, str) or not artifact_uri.startswith("github-actions://"):
        raise ValueError("artifact_remote_uri must be a GitHub Actions artifact URI")

    def child_uri(relative_path: str) -> str:
        encoded = "/".join(quote(part, safe="") for part in relative_path.split("/"))
        return f"{artifact_uri.rstrip('/')}/{encoded}"

    return {
        "version": LOCATOR_VERSION,
        "provider": "github-actions",
        "repository": repository,
        "workflow": workflow,
        "workflow_run_id": run_id,
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "artifact_size_in_bytes": artifact_size,
        "artifact_uri": artifact_uri,
        "render_job_id": render_job_id,
        "video_id": video_id,
        "execution_id": execution_id,
        "media_relative_path": media_relative_path,
        "media_uri": child_uri(media_relative_path),
        "render_job_relative_path": render_job_relative_path,
        "edit_plan_relative_path": edit_plan_relative_path,
        "manifest_relative_path": manifest_relative_path,
        "probe_relative_path": probe_relative_path,
        "qa_relative_path": qa_relative_path,
    }


def validate_media_artifact_locator(
    locator: dict[str, Any],
    *,
    expected_render_job_id: int | None = None,
    expected_video_id: int | None = None,
    expected_execution_id: str | None = None,
) -> dict[str, Any]:
    """Fail closed when a persisted locator loses its exact media lineage."""
    if not isinstance(locator, dict) or locator.get("version") != LOCATOR_VERSION:
        raise ValueError("unsupported media artifact locator")
    if locator.get("provider") != "github-actions":
        raise ValueError("unsupported media artifact provider")
    for field in (
        "workflow_run_id",
        "artifact_id",
        "artifact_size_in_bytes",
        "render_job_id",
        "video_id",
    ):
        _positive_int(locator.get(field), field)
    for field in (
        "repository",
        "workflow",
        "artifact_name",
        "artifact_uri",
        "execution_id",
        "media_relative_path",
        "media_uri",
        "render_job_relative_path",
        "manifest_relative_path",
        "probe_relative_path",
        "qa_relative_path",
    ):
        if not isinstance(locator.get(field), str) or not locator[field].strip():
            raise ValueError(f"locator field is required: {field}")
    if expected_render_job_id is not None and locator["render_job_id"] != expected_render_job_id:
        raise ValueError("media locator render_job_id mismatch")
    if expected_video_id is not None and locator["video_id"] != expected_video_id:
        raise ValueError("media locator video_id mismatch")
    if expected_execution_id is not None and locator["execution_id"] != expected_execution_id:
        raise ValueError("media locator execution_id mismatch")
    expected_prefix = f"{locator['execution_id']}/{locator['render_job_id']}/"
    if not locator["media_relative_path"].startswith(expected_prefix):
        raise ValueError("media locator relative path lineage mismatch")
    if not locator["media_relative_path"].endswith(f"/{locator['video_id']}.mp4"):
        raise ValueError("media locator MP4 identity mismatch")
    if not locator["media_uri"].startswith(locator["artifact_uri"].rstrip("/") + "/"):
        raise ValueError("media locator URI escapes artifact")
    return dict(locator)


__all__ = [
    "LOCATOR_VERSION",
    "build_github_media_artifact_locator",
    "validate_media_artifact_locator",
]
