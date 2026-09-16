from __future__ import annotations

from typing import Any, Callable

from app.services.google_youtube_publication_service import (
    PRIVATE_UPLOAD_CAPABILITY_ID,
    PUBLICATION_CAPABILITY_ID,
    make_youtube_publication_public_with_google,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_execution_result import canonical_execution_result
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.youtube_cloud_upload_service import dispatch_targeted_private_upload
from app.services.youtube_publication_readiness_service import build_youtube_publication_preview


PRIVATE_UPLOAD_EXECUTOR = (
    "app.services.youtube_cloud_upload_service.dispatch_targeted_private_upload"
)
PUBLICATION_EXECUTOR = (
    "app.services.youtube_publication_orchestration.make_youtube_publication_public"
)
USER_APPROVAL_OPERATION = "br_youtube_pode_postar"


def _publication_id(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("publication_id must be a positive integer")
    return value


def _route(*, publication_id: int, capability_id: str, action: str, expected_executor: str):
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"execute {capability_id} for persisted YouTube publication {publication_id}",
            authorized_action=action,
            required_capability_id=capability_id,
            fallback_allowed=False,
        )
    )
    if routing.selected_capability_id != capability_id:
        raise PermissionError("Harness routing selected a different publication capability")
    if routing.selected_executor_binding != expected_executor:
        raise PermissionError("Harness routing selected an unexpected publication executor")
    if routing.fallback_occurred:
        raise PermissionError("YouTube publication capability may not use fallback")
    return routing


def upload_targeted_publication(
    publication_id: int,
    *,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Compatibility boundary: exact uploads now always use the cloud data plane."""
    _ = (token_file, client_secrets_file, authorization_runner, request)
    publication_id = _publication_id(publication_id)
    return dispatch_targeted_private_upload(publication_id)


def publish_targeted_publication(
    publication_id: int,
    *,
    approval_source: str,
    approval_operation: str,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Turn one exact private upload public after explicit user approval.

    Readiness proves technical eligibility; ``approval_source=user`` proves the
    origin of the request.  Neither is a second authority: Harness Routing and
    the persisted PUBLICATION authorization remain the operational authority.
    """
    publication_id = _publication_id(publication_id)
    if approval_source != "user" or approval_operation != USER_APPROVAL_OPERATION:
        raise PermissionError("public publication requires explicit user-originated approval")

    preview = build_youtube_publication_preview(publication_id)
    if preview.get("PUBLICATION_READY") is not True:
        raise ValueError(
            "YouTube publication is not ready for public approval: "
            + "; ".join(str(item) for item in preview.get("reasons") or [])
        )

    routing = _route(
        publication_id=publication_id,
        capability_id=PUBLICATION_CAPABILITY_ID,
        action="PUBLICATION",
        expected_executor=PUBLICATION_EXECUTOR,
    )
    artifact_identity = preview.get("artifact_identity") or {}
    authorization = issue_harness_authorization(
        authorized_action="PUBLICATION",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "publication_id": publication_id,
            "goal_id": preview.get("goal_id"),
            "video_id": preview.get("video_id"),
            "render_job_id": preview.get("render_job_id"),
            "artifact_id": artifact_identity.get("artifact_id"),
            "youtube_video_id": preview.get("youtube_video_id"),
            "approval_source": "user",
            "approval_operation": USER_APPROVAL_OPERATION,
            "fallback_occurred": routing.fallback_occurred,
        },
    )
    result = make_youtube_publication_public_with_google(
        publication_id=publication_id,
        authorization=authorization,
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )
    success = result.get("status") == "published"
    evidence = canonical_execution_result(
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        execution_id=authorization.execution_id,
        routing_id=routing.routing_id,
        authorization_id=authorization.authorization_id,
        harness_decision_id=authorization.harness_decision_id,
        capability_id=routing.selected_capability_id,
        tool="harness_youtube_publication_service",
        operation="publish_targeted_publication",
        executor=routing.selected_executor_binding,
        status="SUCCEEDED" if success else "RECONCILIATION_REQUIRED",
        success=success,
        result=result,
        evidence={
            "publication_id": publication_id,
            "goal_id": preview.get("goal_id"),
            "video_id": preview.get("video_id"),
            "render_job_id": preview.get("render_job_id"),
            "artifact_id": artifact_identity.get("artifact_id"),
            "qa_status": preview.get("qa_status"),
            "approval_source": "user",
            "approval_operation": USER_APPROVAL_OPERATION,
            "fallback_occurred": routing.fallback_occurred,
        },
    )
    return {
        "publication": result,
        "readiness": preview,
        "routing": routing.to_dict(),
        "authorization_id": authorization.authorization_id,
        "canonical_execution_result": evidence.to_dict(),
    }


__all__ = [
    "upload_targeted_publication",
    "publish_targeted_publication",
]
