from __future__ import annotations

from typing import Any

from app.database.gta6_goal_repository import (
    get_gta6_goal_artifacts,
    list_gta6_goals,
)
from app.database.render_queue_repository import get_render_job
from app.database.video_repository import get_video
from app.database.youtube_cloud_execution_repository import get_youtube_cloud_execution
from app.database.youtube_repository import get_youtube_publication
from app.services.media_artifact_locator_service import validate_media_artifact_locator


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _resolve_exact_goal(publication: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    publication_id = _positive_int(publication.get("id"), "publication_id")
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for goal in list_gta6_goals():
        goal_id = goal.get("goal_id")
        if not isinstance(goal_id, str) or not goal_id:
            continue
        artifacts = get_gta6_goal_artifacts(goal_id)
        if isinstance(artifacts, dict) and artifacts.get("youtube_publication_id") == publication_id:
            matches.append((goal, artifacts))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one Goal for YouTube publication {publication_id}; found {len(matches)}"
        )
    return matches[0]


def build_youtube_publication_preview(publication_id: int) -> dict[str, Any]:
    """Return publication readiness without granting authority or mutating state.

    This is deliberately observation-only.  PUBLICATION_READY means the exact
    private upload and its render lineage are technically ready for an explicit
    user-originated ``br_youtube_pode_postar`` command; it is not approval.
    """
    publication_id = _positive_int(publication_id, "publication_id")
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")

    reasons: list[str] = []
    status = publication.get("status")
    if status != "uploaded":
        reasons.append(f"publication_status_is_{status}")
    youtube_video_id = publication.get("youtube_video_id")
    youtube_url = publication.get("youtube_url")
    if not isinstance(youtube_video_id, str) or not youtube_video_id.strip():
        reasons.append("youtube_video_id_missing")
    if not isinstance(youtube_url, str) or not youtube_url.strip():
        reasons.append("youtube_url_missing")

    goal_id: str | None = None
    render_job_id: int | None = None
    artifact_identity: dict[str, Any] | None = None
    qa_status: str | None = None
    try:
        goal, artifacts = _resolve_exact_goal(publication)
        goal_id = goal["goal_id"]
        video_id = _positive_int(publication.get("video_id"), "video_id")
        content_item_id = _positive_int(publication.get("content_item_id"), "content_item_id")
        if artifacts.get("video_id") != video_id:
            raise ValueError("Goal/Publication video_id mismatch")
        if artifacts.get("content_item_id") != content_item_id:
            raise ValueError("Goal/Publication content_item_id mismatch")
        render_job_id = _positive_int(artifacts.get("render_job_id"), "render_job_id")

        video = get_video(video_id)
        if video is None:
            raise ValueError("Goal-linked Video not found")
        if video.get("status") != "ready":
            raise ValueError("Goal-linked Video is not ready")
        if video.get("content_item_id") != content_item_id:
            raise ValueError("Video/Publication content_item_id mismatch")
        if video.get("render_job_id") != render_job_id:
            raise ValueError("Video/Goal render_job_id mismatch")

        render_job = get_render_job(render_job_id)
        if render_job is None or render_job.get("status") != "completed":
            raise ValueError("Goal-linked RenderJob is not completed")
        if render_job.get("video_id") != video_id:
            raise ValueError("RenderJob/Video identity mismatch")
        if render_job.get("content_item_id") != content_item_id:
            raise ValueError("RenderJob/Publication content_item_id mismatch")
        github_execution = render_job.get("github_execution")
        if not isinstance(github_execution, dict):
            raise ValueError("RenderJob has no persisted GitHub execution")
        raw_locator = github_execution.get("artifact_locator")
        locator = validate_media_artifact_locator(
            raw_locator,
            expected_render_job_id=render_job_id,
            expected_video_id=video_id,
            expected_execution_id=render_job.get("execution_id"),
        )
        if publication.get("file_path") != locator["media_uri"]:
            raise ValueError("Publication does not target the QA-proven cloud MP4")
        if video.get("file_path") != locator["media_uri"]:
            raise ValueError("Video does not target the QA-proven cloud MP4")

        cloud = get_youtube_cloud_execution(publication_id)
        if not isinstance(cloud, dict) or cloud.get("status") != "SUCCEEDED":
            raise ValueError("private-upload cloud execution is not SUCCEEDED")
        result = cloud.get("result")
        if not isinstance(result, dict) or result.get("status") != "UPLOADED":
            raise ValueError("private-upload cloud result is not UPLOADED")
        if result.get("publication_id") != publication_id or result.get("video_id") != video_id:
            raise ValueError("private-upload result publication/video mismatch")
        if result.get("youtube_video_id") != youtube_video_id or result.get("youtube_url") != youtube_url:
            raise ValueError("private-upload result YouTube identity mismatch")
        evidence = result.get("artifact_evidence")
        if not isinstance(evidence, dict) or evidence.get("qa_status") != "PASS":
            raise ValueError("private-upload result has no QA PASS artifact evidence")
        expected_evidence = {
            "render_job_id": render_job_id,
            "video_id": video_id,
            "execution_id": locator["execution_id"],
            "workflow_run_id": locator["workflow_run_id"],
            "artifact_id": locator["artifact_id"],
            "media_relative_path": locator["media_relative_path"],
        }
        for key, expected in expected_evidence.items():
            if evidence.get(key) != expected:
                raise ValueError(f"private-upload artifact evidence mismatch: {key}")
        sha256 = evidence.get("sha256")
        size_bytes = evidence.get("size_bytes")
        duration_seconds = evidence.get("duration_seconds")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise ValueError("artifact evidence sha256 is invalid")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes <= 0:
            raise ValueError("artifact evidence size_bytes is invalid")
        if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)) or duration_seconds <= 0:
            raise ValueError("artifact evidence duration_seconds is invalid")
        qa_status = "PASS"
        artifact_identity = {
            "provider": locator["provider"],
            "repository": locator["repository"],
            "workflow": locator["workflow"],
            "workflow_run_id": locator["workflow_run_id"],
            "artifact_id": locator["artifact_id"],
            "artifact_name": locator["artifact_name"],
            "render_job_id": render_job_id,
            "execution_id": locator["execution_id"],
            "media_relative_path": locator["media_relative_path"],
            "media_uri": locator["media_uri"],
            "sha256": sha256,
            "size_bytes": size_bytes,
            "duration_seconds": duration_seconds,
        }
    except (ValueError, RuntimeError) as exc:
        reasons.append(str(exc))

    ready = not reasons
    return {
        "publication_id": publication_id,
        "goal_id": goal_id,
        "video_id": publication.get("video_id"),
        "content_item_id": publication.get("content_item_id"),
        "render_job_id": render_job_id,
        "youtube_video_id": youtube_video_id,
        "youtube_url": youtube_url,
        "title": publication.get("title"),
        "description": publication.get("description"),
        "tags": list(publication.get("tags") or []),
        "category_id": publication.get("category_id"),
        "privacy_status": publication.get("privacy_status"),
        "upload_status": status,
        "qa_status": qa_status,
        "artifact_identity": artifact_identity,
        "analytics_eligible": status in {"uploaded", "published"} and bool(youtube_video_id),
        "PUBLICATION_READY": ready,
        "reasons": reasons if reasons else ["uploaded_private_and_lineage_verified"],
        "approval_granted": False,
        "boundary": "READ_ONLY_NO_PUBLICATION_AUTHORITY",
    }


__all__ = ["build_youtube_publication_preview"]
