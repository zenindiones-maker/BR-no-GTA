from types import SimpleNamespace

import pytest

from app.services import youtube_analytics_learning_service as learning_svc
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.youtube_analytics_service import (
    ANALYTICS_CAPABILITY_ID, ANALYTICS_EXECUTOR_BINDING, ANALYTICS_METRICS,
    read_publication_analytics,
)


def _routing(**changes):
    values = dict(
        routing_id="route-analytics-1", intent="read youtube analytics", authorized_action="EXECUTION",
        candidate_capability_ids=(ANALYTICS_CAPABILITY_ID,), selected_capability_id=ANALYTICS_CAPABILITY_ID,
        selected_provider=None, selected_model=None, selected_executor_binding=ANALYTICS_EXECUTOR_BINDING,
        selected_provider_executor_binding=None, primary_provider=None, fallback_allowed=False,
        fallback_candidates=(), fallback_occurred=False, evidence_expectations=(), rationale=("test",),
        rejected_candidates=(), policy_metadata={},
    )
    values.update(changes)
    return HarnessRoutingDecision(**values)


def _authorization(routing=None, **lineage_changes):
    routing = routing or _routing()
    lineage = {"routing_id": routing.routing_id, "capability_id": ANALYTICS_CAPABILITY_ID,
               "selected_executor_binding": ANALYTICS_EXECUTOR_BINDING}
    lineage.update(lineage_changes)
    return issue_harness_authorization(
        authorized_action="EXECUTION", subject=f"capability:{ANALYTICS_CAPABILITY_ID}",
        execution_id="exec-analytics-1", lineage=lineage,
    )


class _Query:
    def __init__(self, response): self.response = response; self.kwargs = None
    def query(self, **kwargs): self.kwargs = kwargs; return self
    def execute(self): return self.response


class _Service:
    def __init__(self, response): self.query_api = _Query(response)
    def reports(self): return self.query_api


def _credentials():
    return SimpleNamespace(has_scopes=lambda scopes: True)


def _response():
    return {"columnHeaders": [{"name": name} for name in ANALYTICS_METRICS],
            "rows": [[10, 20, 120, 50.0, 3, 2, 1]]}


def _call(monkeypatch, *, authorization=None, routing=None, response=None):
    routing = routing or _routing()
    authorization = authorization or _authorization(routing)
    monkeypatch.setattr("app.services.youtube_analytics_service.get_youtube_publication", lambda publication_id: {
        "id": publication_id, "youtube_video_id": "yt-persisted-123", "video_id": 7, "content_item_id": 8,
    })
    service = _Service(response if response is not None else _response())
    result = read_publication_analytics(
        publication_id=4, start_date="2026-09-01", end_date="2026-09-07",
        authorization=authorization, routing_decision=routing, execution_id="exec-analytics-1",
        token_file="/runtime/token.json", client_secrets_file="/runtime/client.json",
        credentials_loader=lambda **kwargs: _credentials(), service_factory=lambda credentials: service,
    )
    return result, service


def test_registry_declares_bounded_partial_analytics_executor():
    record = GLOBAL_CAPABILITY_REGISTRY.get(ANALYTICS_CAPABILITY_ID)
    assert record is not None and record.maturity == "PARTIAL" and record.allowed_actions == ("EXECUTION",)
    assert record.executor_binding == ANALYTICS_EXECUTOR_BINDING and record.fallback_eligibility is False


def test_valid_route_resolves_persisted_publication_identity_and_canonical_result(monkeypatch):
    result, service = _call(monkeypatch)
    assert result["youtube_video_id"] == "yt-persisted-123"
    assert service.query_api.kwargs["filters"] == "video==yt-persisted-123"
    assert result["metric_window"] == {"start_date": "2026-09-01", "end_date": "2026-09-07"}
    assert result["canonical_execution_result"]["capability_id"] == ANALYTICS_CAPABILITY_ID
    assert result["canonical_execution_result"]["execution_id"] == "exec-analytics-1"


def test_analytics_read_output_is_direct_learning_input(monkeypatch):
    analytics_result, _ = _call(monkeypatch)
    learning_capability = GLOBAL_CAPABILITY_REGISTRY.get(learning_svc.CAPABILITY_ID)
    assert learning_capability is not None

    monkeypatch.setattr(learning_svc, "list_memory_events_by_source", lambda **kwargs: [])
    monkeypatch.setattr(learning_svc, "insert_memory_event", lambda event: 91)

    learning_result = learning_svc.execute_youtube_analytics_learning_capability(
        learning_capability,
        analytics_result,
    )

    assert learning_result["status"] == "LEARNED"
    assert learning_result["memory_event_id"] == 91
    assert learning_result["learning"]["metric_window"] == analytics_result["metric_window"]
    assert learning_result["learning"]["publication_id"] == analytics_result["publication_id"]
    assert learning_result["learning"]["youtube_video_id"] == analytics_result["youtube_video_id"]


def test_missing_and_fabricated_authorization_fail_closed(monkeypatch):
    with pytest.raises(PermissionError):
        _call(monkeypatch, authorization={"authorization_id": "not-persisted"})


def test_wrong_action_fails_closed(monkeypatch):
    auth = issue_harness_authorization(authorized_action="YOUTUBE", subject=f"capability:{ANALYTICS_CAPABILITY_ID}", execution_id="exec-analytics-1")
    with pytest.raises(PermissionError): _call(monkeypatch, authorization=auth)


def test_execution_id_mismatch_fails_closed(monkeypatch):
    auth = issue_harness_authorization(authorized_action="EXECUTION", subject=f"capability:{ANALYTICS_CAPABILITY_ID}", execution_id="different")
    with pytest.raises(PermissionError): _call(monkeypatch, authorization=auth)


@pytest.mark.parametrize("changes", [
    {"capability_id": "phone.control"}, {"selected_executor_binding": "evil.module.callable"},
])
def test_authorization_lineage_mismatch_fails_closed(monkeypatch, changes):
    routing = _routing(); auth = _authorization(routing, **changes)
    with pytest.raises(PermissionError): _call(monkeypatch, authorization=auth, routing=routing)


def test_routing_capability_and_executor_injection_blocked(monkeypatch):
    for routing in (_routing(selected_capability_id="phone.control"), _routing(selected_executor_binding="evil.callable")):
        auth = _authorization(routing)
        with pytest.raises(PermissionError): _call(monkeypatch, authorization=auth, routing=routing)


def test_missing_metrics_are_not_coerced_to_zero(monkeypatch):
    response = {"columnHeaders": [{"name": "views"}], "rows": [[0]]}
    result, _ = _call(monkeypatch, response=response)
    assert result["metrics"]["views"] == {"status": "VALUE", "value": 0}
    assert result["metrics"]["likes"] == {"status": "MISSING", "value": None}


def test_no_data_is_explicit(monkeypatch):
    result, _ = _call(monkeypatch, response={"columnHeaders": [], "rows": []})
    assert result["status"] == "NO_DATA"
    assert all(item["status"] == "MISSING" for item in result["metrics"].values())


def test_result_contains_no_credentials(monkeypatch):
    result, _ = _call(monkeypatch)
    rendered = repr(result).lower()
    assert "access_token" not in rendered and "refresh_token" not in rendered and "client_secret" not in rendered
