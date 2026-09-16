from typing import Any

from app.services.harness_authorization_service import validate_harness_authorization
from app.database.youtube_public_transition_repository import (
    claim_youtube_public_transition,
    finalize_youtube_public_transition,
    get_youtube_public_transition,
    mark_youtube_public_transition_uncertain,
    reconcile_youtube_public_transition,
)
from app.database.youtube_repository import (
    get_youtube_publication,
    mark_youtube_uploaded,
    update_youtube_publication_status,
)
from app.services.youtube_publisher import (
    YouTubePublisher,
    YouTubeUploadResult,
    YouTubeVisibilityResult,
    YouTubeVisibilityStateResult,
)


PUBLIC_CAPABILITY_ID = "youtube.publish-public"
USER_APPROVAL_OPERATION = "br_youtube_pode_postar"


def upload_youtube_publication(
    publication_id: int,
    publisher: YouTubePublisher,
) -> dict[str, Any]:
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")
    if publication["status"] != "pending":
        raise ValueError(f"YouTube publication is not pending: {publication_id}")
    result = publisher.upload(publication)
    if not isinstance(result, YouTubeUploadResult):
        raise TypeError("publisher.upload() must return YouTubeUploadResult")
    if result.success:
        if not result.youtube_video_id:
            raise ValueError("Successful upload must provide youtube_video_id")
        if not result.youtube_url:
            raise ValueError("Successful upload must provide youtube_url")
        updated = mark_youtube_uploaded(
            publication_id,
            result.youtube_video_id,
            result.youtube_url,
        )
        if not updated:
            raise RuntimeError(f"Failed to persist YouTube upload success: {publication_id}")
    else:
        updated = update_youtube_publication_status(
            publication_id,
            "failed",
            error=result.error or "YouTube upload failed",
        )
        if not updated:
            raise RuntimeError(f"Failed to persist YouTube upload failure: {publication_id}")
    persisted = get_youtube_publication(publication_id)
    if persisted is None:
        raise RuntimeError(f"YouTube publication disappeared after upload: {publication_id}")
    return persisted


def _validate_user_publication_authorization(publication_id: int, authorization: object | None):
    auth = validate_harness_authorization(
        authorization or {},
        expected_action="PUBLICATION",
        expected_subject=f"youtube:publication:{publication_id}",
    )
    lineage = auth.lineage if isinstance(auth.lineage, dict) else {}
    if lineage.get("capability_id") != PUBLIC_CAPABILITY_ID:
        raise PermissionError("PUBLICATION authorization capability mismatch")
    if lineage.get("publication_id") != publication_id:
        raise PermissionError("PUBLICATION authorization publication_id mismatch")
    if lineage.get("fallback_occurred") is not False:
        raise PermissionError("PUBLICATION authorization may not use fallback")
    if lineage.get("approval_source") != "user":
        raise PermissionError("public publication requires explicit user approval evidence")
    if lineage.get("approval_operation") != USER_APPROVAL_OPERATION:
        raise PermissionError("public publication approval operation mismatch")
    return auth


def make_youtube_publication_public(
    publication_id: int,
    publisher: YouTubePublisher,
    *,
    authorization: object | None = None,
) -> dict[str, Any]:
    """Execute one user-approved uploaded->public side effect exactly once.

    The authorization is consumed atomically with the persisted EXECUTING claim
    before calling YouTube.  Any uncertainty after that point requires remote
    visibility reconciliation and may never cause a blind repeat.
    """
    auth = _validate_user_publication_authorization(publication_id, authorization)
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")
    if publication["status"] != "uploaded":
        raise ValueError(f"YouTube publication is not uploaded: {publication_id}")
    youtube_video_id = publication.get("youtube_video_id")
    if not isinstance(youtube_video_id, str) or not youtube_video_id.strip():
        raise ValueError("Uploaded YouTube publication must have youtube_video_id")
    if not isinstance(publication.get("youtube_url"), str) or not publication["youtube_url"].strip():
        raise ValueError("Uploaded YouTube publication must have youtube_url")

    claim_youtube_public_transition(
        publication_id,
        authorization_id=auth.authorization_id,
        execution_id=auth.execution_id,
        routing_id=str(auth.lineage.get("routing_id") or ""),
        youtube_video_id=youtube_video_id,
        approval_source="user",
        approval_operation=USER_APPROVAL_OPERATION,
    )

    try:
        result = publisher.make_public(youtube_video_id)
    except Exception as exc:
        try:
            mark_youtube_public_transition_uncertain(
                publication_id,
                expected_authorization_id=auth.authorization_id,
                error=f"publisher raised after public-transition claim: {exc}",
            )
        finally:
            raise RuntimeError("YouTube public side effect is uncertain; reconciliation is required") from exc

    if not isinstance(result, YouTubeVisibilityResult):
        mark_youtube_public_transition_uncertain(
            publication_id,
            expected_authorization_id=auth.authorization_id,
            error="publisher.make_public returned invalid result type",
        )
        raise TypeError("publisher.make_public() must return YouTubeVisibilityResult")

    if not result.success:
        mark_youtube_public_transition_uncertain(
            publication_id,
            expected_authorization_id=auth.authorization_id,
            error=result.error or "YouTube visibility update outcome is uncertain",
        )
        persisted = get_youtube_publication(publication_id)
        if persisted is None:
            raise RuntimeError("YouTube publication disappeared after visibility uncertainty")
        persisted = dict(persisted)
        persisted["publication_transition"] = "REMOTE_STATE_UNCERTAIN"
        persisted["error"] = result.error or "YouTube visibility update outcome is uncertain"
        return persisted

    try:
        finalize_youtube_public_transition(
            publication_id,
            expected_authorization_id=auth.authorization_id,
        )
    except Exception as exc:
        try:
            mark_youtube_public_transition_uncertain(
                publication_id,
                expected_authorization_id=auth.authorization_id,
                error=f"remote success observed but local finalization failed: {exc}",
            )
        except Exception:
            pass
        raise RuntimeError(
            "YouTube became public but local finalization is uncertain; remote reconciliation is required"
        ) from exc

    persisted = get_youtube_publication(publication_id)
    if persisted is None or persisted.get("status") != "published":
        raise RuntimeError("YouTube publication was not persisted as published")
    return persisted


def reconcile_youtube_publication_visibility(
    publication_id: int,
    publisher: YouTubePublisher,
) -> dict[str, Any]:
    """Read remote state and reconcile a previously user-approved transition."""
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")
    if publication.get("status") == "published":
        return publication
    if publication.get("status") != "uploaded":
        raise ValueError("YouTube publication is not reconcilable from current status")
    transition = get_youtube_public_transition(publication_id)
    if not isinstance(transition, dict) or transition.get("status") not in {
        "EXECUTING",
        "REMOTE_STATE_UNCERTAIN",
    }:
        raise ValueError("YouTube publication has no uncertain public transition")
    youtube_video_id = publication.get("youtube_video_id")
    result = publisher.get_visibility(youtube_video_id)
    if not isinstance(result, YouTubeVisibilityStateResult):
        raise TypeError("publisher.get_visibility() must return YouTubeVisibilityStateResult")
    if not result.success or result.privacy_status not in {"public", "private", "unlisted"}:
        raise RuntimeError(result.error or "YouTube remote visibility could not be confirmed")
    reconcile_youtube_public_transition(
        publication_id,
        remote_privacy_status=result.privacy_status,
    )
    persisted = get_youtube_publication(publication_id)
    if persisted is None:
        raise RuntimeError("YouTube publication disappeared after reconciliation")
    return persisted


__all__ = [
    "upload_youtube_publication",
    "make_youtube_publication_public",
    "reconcile_youtube_publication_visibility",
]
