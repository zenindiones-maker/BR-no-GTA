from __future__ import annotations

from typing import Any, Callable

from app.services.google_youtube_publication_service import (
    PRIVATE_UPLOAD_CAPABILITY_ID,
    PUBLICATION_CAPABILITY_ID,
    make_youtube_publication_public_with_google,
    process_youtube_publication,
)
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.harness_execution_result import canonical_execution_result
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)


def _publication_id(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("publication_id must be a positive integer")
    return value


def _route(*, publication_id: int, capability_id: str, action: str):
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
    """Route, authorize and upload exactly one persisted Publication as private."""
    publication_id = _publication_id(publication_id)
    routing = _route(
        publication_id=publication_id,
        capability_id=PRIVATE_UPLOAD_CAPABILITY_ID,
        action="YOUTUBE",
    )
    authorization = issue_harness_authorization(
        authorized_action="YOUTUBE",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "publication_id": publication_id,
            "fallback_occurred": routing.fallback_occurred,
        },
    )
    result = process_youtube_publication(
        publication_id,
        authorization_to_context(authorization),
        token_file=token_file,
        client_secrets_file=client_secrets_file,
        authorization_runner=authorization_runner,
        request=request,
    )
    evidence = canonical_execution_result(
        authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        execution_id=authorization.execution_id,
        routing_id=routing.routing_id,
        authorization_id=authorization.authorization_id,
        harness_decision_id=authorization.harness_decision_id,
        capability_id=routing.selected_capability_id,
        tool="harness_youtube_publication_service",
        operation="upload_targeted_publication",
        executor=routing.selected_executor_binding,
        status="SUCCEEDED" if result.get("status") == "uploaded" else "FAILED",
        success=result.get("status") == "uploaded",
        result=result,
        evidence={
            "publication_id": publication_id,
            "fallback_occurred": routing.fallback_occurred,
        },
    )
    return {
        "publication": result,
        "routing": routing.to_dict(),
        "authorization_id": authorization.authorization_id,
        "canonical_execution_result": evidence.to_dict(),
    }


def publish_targeted_publication(
    publication_id: int,
    *,
    token_file: str | None = None,
    client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None,
    request: Any | None = None,
) -> dict[str, Any]:
    """Route and authorize the uploaded -> published transition for one Publication."""
    publication_id = _publication_id(publication_id)
    routing = _route(
        publication_id=publication_id,
        capability_id=PUBLICATION_CAPABILITY_ID,
        action="PUBLICATION",
    )
    authorization = issue_harness_authorization(
        authorized_action="PUBLICATION",
        subject=f"youtube:publication:{publication_id}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "publication_id": publication_id,
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
        status="SUCCEEDED" if success else "FAILED",
        success=success,
        result=result,
        evidence={
            "publication_id": publication_id,
            "fallback_occurred": routing.fallback_occurred,
        },
    )
    return {
        "publication": result,
        "routing": routing.to_dict(),
        "authorization_id": authorization.authorization_id,
        "canonical_execution_result": evidence.to_dict(),
    }


__all__ = [
    "upload_targeted_publication",
    "publish_targeted_publication",
]
