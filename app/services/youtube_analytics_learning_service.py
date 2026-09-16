from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database.memory_event_repository import insert_memory_event, list_memory_events_by_source
from app.services.memory_event_service import create_memory_event
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import validate_harness_authorization
from app.services.harness_capability_service import CapabilityEvidence, CapabilityExecutionBlocked
from app.services.harness_execution_result import canonical_execution_result

CAPABILITY_ID = "knowledge.learn.youtube-analytics"
EXECUTOR_BINDING = "app.services.youtube_analytics_learning_service.execute_youtube_analytics_learning_capability"
SOURCE_CAPABILITY_ID = "youtube.analytics.read"
METRICS = ("views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "likes", "comments", "shares")


def _blocked(message: str, stage: str) -> CapabilityExecutionBlocked:
    return CapabilityExecutionBlocked(message, stage=stage, boundary="analytics learning failed closed")


def _validate_source(source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source, dict) or source.get("source") != "youtube_analytics" or source.get("capability_id") != SOURCE_CAPABILITY_ID:
        raise _blocked("analytics evidence provenance is invalid", "evidence")
    publication_id = source.get("publication_id")
    youtube_video_id = source.get("youtube_video_id")
    window = source.get("metric_window")
    metrics = source.get("metrics")
    if isinstance(publication_id, bool) or not isinstance(publication_id, int) or publication_id <= 0:
        raise _blocked("persisted publication_id is required", "evidence")
    if not isinstance(youtube_video_id, str) or not youtube_video_id.strip():
        raise _blocked("persisted youtube_video_id is required", "evidence")
    if (
        not isinstance(window, dict)
        or not window.get("start_date")
        or not window.get("end_date")
    ):
        raise _blocked("analytics metric window is required", "evidence")
    if set(window) != {"start_date", "end_date"}:
        raise _blocked("analytics metric window must use canonical start_date/end_date keys", "evidence")
    if not isinstance(metrics, dict):
        raise _blocked("normalized analytics metrics are required", "evidence")
    normalized: dict[str, dict[str, Any]] = {}
    for name in METRICS:
        item = metrics.get(name)
        if not isinstance(item, dict) or item.get("status") not in {"VALUE", "MISSING"}:
            raise _blocked(f"metric {name} is not normalized", "evidence")
        if item["status"] == "MISSING" and item.get("value") is not None:
            raise _blocked(f"metric {name} MISSING must remain null", "evidence")
        normalized[name] = {"status": item["status"], "value": item.get("value")}
    result = dict(source)
    result["metrics"] = normalized
    return result


def _key(source: dict[str, Any]) -> str:
    identity = {"publication_id": source["publication_id"], "youtube_video_id": source["youtube_video_id"], "metric_window": source["metric_window"], "metrics": source["metrics"]}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _validate_boundary(*, authorization: Any, routing_decision: Any, execution_id: str):
    try:
        auth = validate_harness_authorization(authorization, expected_action="EXECUTION", expected_subject=f"capability:{CAPABILITY_ID}", expected_execution_id=execution_id)
    except PermissionError as exc:
        raise _blocked(str(exc), "authorization") from exc
    capability = GLOBAL_CAPABILITY_REGISTRY.get(CAPABILITY_ID)
    if capability is None or capability.executor_binding != EXECUTOR_BINDING:
        raise _blocked("analytics learning Registry binding is invalid", "binding")
    if routing_decision.selected_capability_id != CAPABILITY_ID or routing_decision.selected_executor_binding != EXECUTOR_BINDING:
        raise _blocked("analytics learning routing binding is invalid", "routing")
    lineage = auth.lineage or {}
    if lineage.get("routing_id") != routing_decision.routing_id or lineage.get("capability_id") != CAPABILITY_ID or lineage.get("selected_executor_binding") != EXECUTOR_BINDING:
        raise _blocked("analytics learning authorization lineage is invalid", "authorization")
    return auth, capability


def execute_youtube_analytics_learning_capability(capability: Any, payload: dict[str, Any]) -> dict[str, Any]:
    if getattr(capability, "capability_id", None) != CAPABILITY_ID or getattr(capability, "executor_binding", None) != EXECUTOR_BINDING:
        raise _blocked("analytics learning executor binding mismatch", "binding")
    source = _validate_source(payload)
    key = _key(source)
    source_id = f"publication:{source['publication_id']}:window:{key}"
    existing = list_memory_events_by_source(source_type="youtube_analytics", source_id=source_id)
    if existing:
        return {"status": "ALREADY_LEARNED", "idempotency_key": key, "memory_event_id": existing[0].get("id"), "learning": source}
    event = create_memory_event(event_type="youtube_analytics_observed", source_type="youtube_analytics", source_id=source_id, scope="gta6", content=f"YouTube Analytics observation for persisted publication {source['publication_id']}.", provenance="youtube_analytics_learning", metadata={"idempotency_key": key, "publication_id": source["publication_id"], "youtube_video_id": source["youtube_video_id"], "metric_window": source["metric_window"], "retrieved_at": source.get("retrieved_at"), "metrics": source["metrics"], "source_execution_id": source.get("execution_id"), "source_authorization_id": source.get("authorization_id"), "source_capability_id": SOURCE_CAPABILITY_ID})
    event_id = insert_memory_event(event)
    return {"status": "LEARNED", "idempotency_key": key, "memory_event_id": event_id, "learning": source}


def learn_from_youtube_analytics(*, analytics_evidence: dict[str, Any], authorization: Any, routing_decision: Any, execution_id: str) -> dict[str, Any]:
    auth, capability = _validate_boundary(authorization=authorization, routing_decision=routing_decision, execution_id=execution_id)
    result = execute_youtube_analytics_learning_capability(capability, analytics_evidence)
    evidence = CapabilityEvidence(capability_id=CAPABILITY_ID, status="EXECUTED", authority=auth.authority, authorized_action=auth.authorized_action, authorization_id=auth.authorization_id, harness_decision_id=auth.harness_decision_id, execution_id=auth.execution_id, result=result)
    canonical = canonical_execution_result(authority=auth.authority, authorized_action=auth.authorized_action, execution_id=auth.execution_id, routing_id=routing_decision.routing_id, authorization_id=auth.authorization_id, harness_decision_id=auth.harness_decision_id, capability_id=CAPABILITY_ID, tool="youtube_analytics_learning_service", operation="learn_from_youtube_analytics", executor=EXECUTOR_BINDING, status="SUCCEEDED", success=True, result=result, evidence={"source_capability_id": SOURCE_CAPABILITY_ID, "idempotency_key": result["idempotency_key"]})
    return {"result": result, "capability_evidence": evidence.to_dict(), "canonical_execution_result": canonical.to_dict()}
