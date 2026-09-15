from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable

from app.database.youtube_repository import get_youtube_publication
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.google_oauth import get_youtube_credentials
from app.services.google_youtube_analytics_client import (
    YOUTUBE_ANALYTICS_READ_SCOPE,
    YouTubeAnalyticsScopeError,
    create_youtube_analytics_service,
)
from app.services.google_youtube_configuration import (
    get_youtube_client_secrets_file,
    get_youtube_token_file,
)
from app.services.harness_authorization_service import HarnessAuthorization, validate_harness_authorization
from app.services.harness_capability_service import CapabilityEvidence
from app.services.harness_routing_policy_service import HarnessRoutingDecision

ANALYTICS_CAPABILITY_ID = "youtube.analytics.read"
ANALYTICS_EXECUTOR_BINDING = "app.services.youtube_analytics_service.execute_youtube_analytics_read_capability"
ANALYTICS_METRICS = (
    "views",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "comments",
    "shares",
)


def _validate_date(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be YYYY-MM-DD")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValueError(f"{name} must be YYYY-MM-DD") from exc


def _validate_boundary(*, authorization: HarnessAuthorization | dict[str, Any] | str,
                       routing_decision: HarnessRoutingDecision, execution_id: str) -> tuple[HarnessAuthorization, Any]:
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise PermissionError("analytics execution_id is required")
    authorization = validate_harness_authorization(
        authorization,
        expected_action="EXECUTION",
        expected_subject=f"capability:{ANALYTICS_CAPABILITY_ID}",
        expected_execution_id=execution_id,
    )
    record = GLOBAL_CAPABILITY_REGISTRY.get(ANALYTICS_CAPABILITY_ID)
    if record is None or not record.execution_enabled:
        raise PermissionError("analytics capability is not executable")
    if record.executor_binding != ANALYTICS_EXECUTOR_BINDING:
        raise PermissionError("analytics Registry executor mismatch")
    if routing_decision.authorized_action != "EXECUTION":
        raise PermissionError("analytics routing action mismatch")
    if routing_decision.selected_capability_id != ANALYTICS_CAPABILITY_ID:
        raise PermissionError("analytics routing capability mismatch")
    if routing_decision.selected_executor_binding != ANALYTICS_EXECUTOR_BINDING:
        raise PermissionError("analytics routing executor mismatch")
    lineage = authorization.lineage
    if lineage.get("routing_id") != routing_decision.routing_id:
        raise PermissionError("analytics authorization routing mismatch")
    if lineage.get("capability_id") != ANALYTICS_CAPABILITY_ID:
        raise PermissionError("analytics authorization capability mismatch")
    if lineage.get("selected_executor_binding") != ANALYTICS_EXECUTOR_BINDING:
        raise PermissionError("analytics authorization executor mismatch")
    return authorization, record


def _normalize_metrics(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    columns = response.get("columnHeaders") or []
    rows = response.get("rows") or []
    names = [item.get("name") for item in columns if isinstance(item, dict)]
    values = rows[0] if rows and isinstance(rows[0], list) else []
    by_name = {name: values[index] for index, name in enumerate(names) if isinstance(name, str) and index < len(values)}
    return {
        metric: ({"status": "VALUE", "value": by_name[metric]} if metric in by_name
                 else {"status": "MISSING", "value": None})
        for metric in ANALYTICS_METRICS
    }


def execute_youtube_analytics_read_capability(
    capability: Any,
    *,
    youtube_video_id: str,
    start_date: str,
    end_date: str,
    credentials: Any,
    service_factory: Callable[[Any], Any] = create_youtube_analytics_service,
) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != ANALYTICS_CAPABILITY_ID:
        raise PermissionError("analytics executor received a different capability")
    if getattr(capability, "executor_binding", None) != ANALYTICS_EXECUTOR_BINDING:
        raise PermissionError("analytics executor binding mismatch")
    if not isinstance(youtube_video_id, str) or not youtube_video_id.strip():
        raise ValueError("persisted youtube_video_id is required")
    analytics = service_factory(credentials)
    response = analytics.reports().query(
        ids="channel==MINE",
        startDate=start_date,
        endDate=end_date,
        metrics=",".join(ANALYTICS_METRICS),
        filters=f"video=={youtube_video_id.strip()}",
    ).execute()
    if not isinstance(response, dict):
        raise RuntimeError("YouTube Analytics returned an invalid response")
    return {"metrics": _normalize_metrics(response), "has_data": bool(response.get("rows"))}


def read_publication_analytics(
    *, publication_id: int, start_date: str, end_date: str,
    authorization: HarnessAuthorization | dict[str, Any] | str,
    routing_decision: HarnessRoutingDecision, execution_id: str,
    token_file: str | None = None, client_secrets_file: str | None = None,
    authorization_runner: Callable[[Any], Any] | None = None, request: Any | None = None,
    credentials_loader: Callable[..., Any] = get_youtube_credentials,
    service_factory: Callable[[Any], Any] = create_youtube_analytics_service,
) -> dict[str, Any]:
    start_date = _validate_date(start_date, "start_date")
    end_date = _validate_date(end_date, "end_date")
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    if not isinstance(publication_id, int) or isinstance(publication_id, bool) or publication_id <= 0:
        raise ValueError("publication_id must be a positive integer")
    authorization, record = _validate_boundary(
        authorization=authorization, routing_decision=routing_decision, execution_id=execution_id
    )
    publication = get_youtube_publication(publication_id)
    if publication is None:
        raise ValueError(f"YouTube publication not found: {publication_id}")
    youtube_video_id = publication.get("youtube_video_id")
    if not isinstance(youtube_video_id, str) or not youtube_video_id.strip():
        raise RuntimeError("publication has no persisted youtube_video_id")
    resolved_token = token_file if token_file is not None else get_youtube_token_file()
    resolved_secrets = client_secrets_file if client_secrets_file is not None else get_youtube_client_secrets_file()
    credentials = credentials_loader(
        token_file=resolved_token,
        client_secrets_file=resolved_secrets,
        authorization_runner=authorization_runner,
        request=request,
        scopes=(YOUTUBE_ANALYTICS_READ_SCOPE,),
    )
    result = execute_youtube_analytics_read_capability(
        record, youtube_video_id=youtube_video_id, start_date=start_date, end_date=end_date,
        credentials=credentials, service_factory=service_factory,
    )
    retrieved_at = datetime.now(timezone.utc).isoformat()
    normalized = {
        "source": "youtube_analytics",
        "publication_id": publication_id,
        "youtube_video_id": youtube_video_id,
        "video_id": publication.get("video_id"),
        "content_item_id": publication.get("content_item_id"),
        "metric_window": {"start_date": start_date, "end_date": end_date},
        "retrieved_at": retrieved_at,
        "metrics": result["metrics"],
        "status": "SUCCESS" if result["has_data"] else "NO_DATA",
        "execution_id": authorization.execution_id,
        "authorization_id": authorization.authorization_id,
        "capability_id": ANALYTICS_CAPABILITY_ID,
    }
    evidence = CapabilityEvidence(
        capability_id=ANALYTICS_CAPABILITY_ID, provider=record.provider,
        status="EXECUTED", active=True, authority=authorization.authority,
        authorized_action=authorization.authorized_action,
        harness_decision_id=authorization.harness_decision_id,
        execution_id=authorization.execution_id, result=normalized,
        boundary=record.security_boundary,
    )
    canonical = evidence.to_canonical_result(
        authorization_id=authorization.authorization_id, routing_id=routing_decision.routing_id,
        executor=ANALYTICS_EXECUTOR_BINDING, operation="read_publication_analytics",
    )
    return {**normalized, "capability_evidence": evidence.to_dict(), "canonical_execution_result": canonical.to_dict()}


__all__ = [
    "ANALYTICS_CAPABILITY_ID", "ANALYTICS_EXECUTOR_BINDING", "ANALYTICS_METRICS",
    "YouTubeAnalyticsScopeError", "read_publication_analytics",
]
