from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import app.settings as app_settings
from app.database.render_queue_repository import list_render_jobs
from app.database.youtube_cloud_execution_repository import (
    bind_youtube_cloud_run,
    claim_youtube_cloud_execution,
    get_youtube_cloud_execution,
    mark_youtube_cloud_dispatch_uncertain,
    record_youtube_cloud_failure,
    reconcile_youtube_cloud_upload_success,
    reset_recoverable_youtube_cloud_dispatch_uncertain,
)
from app.database.youtube_repository import get_youtube_publication
from app.services.github_actions_artifact_service import GitHubActionsArtifactService
from app.services.github_actions_command_runner import run_github_actions_command
from app.services.github_actions_dispatcher import GitHubActionsDispatcher
from app.services.github_actions_run_tracker import GitHubActionsRunTracker
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_execution_result import canonical_execution_result
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.media_artifact_locator_service import validate_media_artifact_locator


CAPABILITY_ID = "youtube.upload-private"
EXECUTOR_BINDING = "app.services.youtube_cloud_upload_service.dispatch_targeted_private_upload"
WORKFLOW = "youtube-private-upload-worker.yml"


def _publication(publication_id: int) -> dict[str, Any]:
    if isinstance(publication_id, bool) or not isinstance(publication_id, int) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")
    if publication.get("status") != "pending":
        raise ValueError(f"YouTube publication is not pending: {publication_id}")
    return publication


def _render_locator_for_video(video_id: int) -> dict[str, Any]:
    matches = []
    for job in list_render_jobs():
        github_execution = job.get("github_execution")
        locator = github_execution.get("artifact_locator") if isinstance(github_execution, dict) else None
        if (
            job.get("status") == "completed"
            and job.get("video_id") == video_id
            and isinstance(locator, dict)
        ):
            matches.append((job, locator))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one completed QA-proven RenderJob for video {video_id}; found {len(matches)}"
        )
    job, raw_locator = matches[0]
    locator = validate_media_artifact_locator(
        raw_locator,
        expected_render_job_id=job.get("id"),
        expected_video_id=video_id,
        expected_execution_id=job.get("execution_id"),
    )
    return locator


def _route(publication_id: int):
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"upload persisted YouTube publication {publication_id} as private through cloud worker",
            authorized_action="YOUTUBE",
            required_capability_id=CAPABILITY_ID,
            fallback_allowed=False,
        )
    )
    if routing.selected_capability_id != CAPABILITY_ID:
        raise PermissionError("Harness routing selected a different YouTube upload capability")
    if routing.selected_executor_binding != EXECUTOR_BINDING:
        raise PermissionError("Harness routing selected an unexpected YouTube upload executor")
    if routing.fallback_occurred:
        raise PermissionError("YouTube private upload may not use fallback")
    return routing


def _issue(publication_id: int, routing, *, operation: str):
    return issue_harness_authorization(
        authorized_action="YOUTUBE",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
            "publication_id": publication_id,
            "operation": operation,
            "fallback_occurred": routing.fallback_occurred,
        },
    )


def _build_upload_job(
    publication: dict[str, Any],
    locator: dict[str, Any],
    *,
    routing_id: str,
    authorization_id: str,
    execution_id: str,
) -> dict[str, Any]:
    if publication.get("video_id") != locator.get("video_id"):
        raise ValueError("Publication/RenderJob video identity mismatch")
    if publication.get("file_path") != locator.get("media_uri"):
        raise ValueError("Publication file_path does not match the exact QA-proven cloud MP4 locator")
    if publication.get("privacy_status") != "private":
        raise ValueError("Private upload requires publication privacy_status=private")
    return {
        "publication_id": publication["id"],
        "video_id": publication["video_id"],
        "content_item_id": publication["content_item_id"],
        "title": publication["title"],
        "description": publication.get("description") or "",
        "tags": list(publication.get("tags") or []),
        "category_id": publication.get("category_id") or "20",
        "privacy_status": "private",
        "authorized_action": "YOUTUBE",
        "capability_id": CAPABILITY_ID,
        "routing_id": routing_id,
        "authorization_id": authorization_id,
        "execution_id": execution_id,
        "artifact_locator": locator,
    }


def _default_repository() -> str:
    repository = app_settings.GITHUB_ACTIONS_REPOSITORY
    if not isinstance(repository, str) or not repository.strip():
        raise RuntimeError("GITHUB_ACTIONS_REPOSITORY is required for cloud YouTube upload")
    return repository.strip()


def _default_ref() -> str:
    ref = app_settings.GITHUB_ACTIONS_RENDER_REF
    if not isinstance(ref, str) or not ref.strip():
        raise RuntimeError("GITHUB_ACTIONS_RENDER_REF is required for cloud YouTube upload")
    return ref.strip()


def dispatch_targeted_private_upload(
    publication_id: int,
    *,
    dispatcher: GitHubActionsDispatcher | None = None,
    repository: str | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    """Dispatch one exact pending Publication to the cloud media data plane.

    The canonical SQLite database is claimed before dispatch, so a process
    restart cannot silently dispatch the same Publication twice.  An uncertain
    dispatch is deliberately fail-closed until its GitHub evidence is resolved.
    """
    publication = _publication(publication_id)
    existing_cloud = get_youtube_cloud_execution(publication_id)
    if existing_cloud is not None:
        if existing_cloud.get("status") != "DISPATCH_UNCERTAIN":
            raise ValueError(f"YouTube publication already has cloud execution: {publication_id}")
        reset_recoverable_youtube_cloud_dispatch_uncertain(
            publication_id,
            expected_workflow=WORKFLOW,
        )
        if get_youtube_cloud_execution(publication_id) is not None:
            raise RuntimeError("recoverable YouTube cloud execution was not cleared")
    locator = _render_locator_for_video(publication["video_id"])
    routing = _route(publication_id)
    authorization = _issue(publication_id, routing, operation="dispatch")
    upload_job = _build_upload_job(
        publication,
        locator,
        routing_id=routing.routing_id,
        authorization_id=authorization.authorization_id,
        execution_id=authorization.execution_id,
    )
    try:
        claim_youtube_cloud_execution(
            publication_id,
            execution_id=authorization.execution_id,
            routing_id=routing.routing_id,
            authorization_id=authorization.authorization_id,
        )
    except Exception:
        consume_harness_authorization(authorization)
        raise

    repository = (repository or _default_repository()).strip()
    ref = (ref or _default_ref()).strip()
    dispatcher = dispatcher or GitHubActionsDispatcher(command_runner=run_github_actions_command)
    encoded_job = base64.b64encode(
        json.dumps(upload_job, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    result_artifact_name = (
        f"youtube-private-upload-result-{publication_id}-{authorization.execution_id}"
    )
    try:
        dispatched = dispatcher.dispatch(
            repository=repository,
            workflow=WORKFLOW,
            ref=ref,
            inputs={
                "publication_id": str(publication_id),
                "execution_id": authorization.execution_id,
                "render_run_id": str(locator["workflow_run_id"]),
                "render_artifact_name": locator["artifact_name"],
                "upload_job_b64": encoded_job,
            },
        )
        cloud = bind_youtube_cloud_run(
            publication_id,
            expected_execution_id=authorization.execution_id,
            github_execution={
                "run_id": dispatched.run_id,
                "repository": repository,
                "workflow": WORKFLOW,
                "ref": ref,
                "result_artifact_name": result_artifact_name,
            },
        )
    except Exception as exc:
        try:
            mark_youtube_cloud_dispatch_uncertain(
                publication_id,
                expected_execution_id=authorization.execution_id,
                error=str(exc),
            )
        finally:
            consume_harness_authorization(authorization)
        raise
    consume_harness_authorization(authorization)

    evidence = canonical_execution_result(
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        execution_id=authorization.execution_id,
        routing_id=routing.routing_id,
        authorization_id=authorization.authorization_id,
        harness_decision_id=authorization.harness_decision_id,
        capability_id=CAPABILITY_ID,
        tool="youtube_cloud_upload_service",
        operation="dispatch_targeted_private_upload",
        executor=EXECUTOR_BINDING,
        status="PENDING",
        success=True,
        result=cloud,
        evidence={
            "publication_id": publication_id,
            "video_id": publication["video_id"],
            "render_job_id": locator["render_job_id"],
            "render_run_id": locator["workflow_run_id"],
            "artifact_id": locator["artifact_id"],
            "upload_run_id": cloud["run_id"],
            "fallback_occurred": False,
        },
    )
    return {
        "status": "IN_PROGRESS",
        "publication_id": publication_id,
        "video_id": publication["video_id"],
        "render_job_id": locator["render_job_id"],
        "render_run_id": locator["workflow_run_id"],
        "render_artifact_id": locator["artifact_id"],
        "upload_run_id": cloud["run_id"],
        "execution_id": authorization.execution_id,
        "routing_id": routing.routing_id,
        "authorization_id": authorization.authorization_id,
        "canonical_execution_result": evidence.to_dict(),
    }


def _load_result_artifact(output_dir: Path) -> dict[str, Any]:
    matches = sorted(output_dir.rglob("youtube-upload-result.json"))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one youtube-upload-result.json; found {len(matches)}"
        )
    try:
        result = json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("YouTube cloud result artifact is invalid JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("YouTube cloud result artifact must be an object")
    return result


def reconcile_targeted_private_upload(
    publication_id: int,
    *,
    tracker: GitHubActionsRunTracker | None = None,
    artifact_service: GitHubActionsArtifactService | None = None,
    result_root: str | Path = "runtime/youtube-upload/results",
) -> dict[str, Any]:
    """Reconcile only the lightweight cloud result into canonical SQLite."""
    publication = _publication(publication_id)
    cloud = get_youtube_cloud_execution(publication_id)
    if not isinstance(cloud, dict) or cloud.get("status") != "IN_PROGRESS":
        raise ValueError("Publication has no IN_PROGRESS private-upload cloud execution")
    routing = _route(publication_id)
    authorization = _issue(publication_id, routing, operation="reconcile")
    if cloud.get("capability_id") != CAPABILITY_ID:
        consume_harness_authorization(authorization)
        raise PermissionError("persisted cloud capability mismatch")
    run_id = cloud.get("run_id")
    repository = cloud.get("repository")
    artifact_name = cloud.get("result_artifact_name")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        consume_harness_authorization(authorization)
        raise ValueError("persisted upload run_id is invalid")
    if not isinstance(repository, str) or repository.count("/") != 1:
        consume_harness_authorization(authorization)
        raise ValueError("persisted upload repository is invalid")
    if not isinstance(artifact_name, str) or not artifact_name:
        consume_harness_authorization(authorization)
        raise ValueError("persisted upload result artifact is invalid")

    tracker = tracker or GitHubActionsRunTracker(command_runner=run_github_actions_command)
    status = tracker.get_status(repository=repository, run_id=run_id)
    if not status.completed:
        consume_harness_authorization(authorization)
        return {
            "status": "IN_PROGRESS",
            "publication_id": publication_id,
            "upload_run_id": run_id,
            "run_status": status.status,
        }
    if not status.succeeded:
        error = (
            f"YouTube private-upload workflow did not succeed: "
            f"status={status.status} conclusion={status.conclusion}"
        )
        record_youtube_cloud_failure(
            publication_id,
            expected_run_id=run_id,
            error=error,
        )
        consume_harness_authorization(authorization)
        return {
            "status": "FAILED",
            "publication_id": publication_id,
            "upload_run_id": run_id,
            "error": error,
        }

    artifact_service = artifact_service or GitHubActionsArtifactService(
        command_runner=run_github_actions_command
    )
    output_dir = Path(result_root) / str(publication_id) / str(run_id)
    artifact_service.download(
        repository=repository,
        run_id=run_id,
        artifact_name=artifact_name,
        output_dir=output_dir,
    )
    result = _load_result_artifact(output_dir)
    cloud_result = reconcile_youtube_cloud_upload_success(
        publication_id,
        expected_run_id=run_id,
        result=result,
    )
    consume_harness_authorization(authorization)
    persisted = get_youtube_publication(publication_id)
    if persisted is None or persisted.get("status") != "uploaded":
        raise RuntimeError("YouTube Publication was not persisted as uploaded")
    return {
        "status": "UPLOADED",
        "publication": persisted,
        "upload_run_id": run_id,
        "cloud_execution": cloud_result,
        "reconciliation_authorization_id": authorization.authorization_id,
        "routing_id": routing.routing_id,
    }


__all__ = [
    "CAPABILITY_ID",
    "EXECUTOR_BINDING",
    "WORKFLOW",
    "dispatch_targeted_private_upload",
    "reconcile_targeted_private_upload",
]
