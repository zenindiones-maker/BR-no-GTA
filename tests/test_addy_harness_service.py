from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.services.addy_harness_service as service
from app.services.harness_ai_provider_service import HarnessAIProviderEvidence
from app.services.harness_authorization_service import HarnessAuthorization
from app.services.harness_routing_policy_service import HarnessRoutingDecision


def _auth(subject: str) -> HarnessAuthorization:
    return HarnessAuthorization(
        authorization_id="auth-test",
        harness_decision_id="decision-test",
        execution_id="execution-test",
        authorized_action="DEVELOPMENT",
        subject=subject,
        issued_by="deepseek_harness",
        issued_at=datetime.now(timezone.utc).isoformat(),
        status="active",
        lineage={
            "routing_id": "addy-routing",
            "capability_id": "addy:debugging-and-error-recovery",
            "selected_executor_binding": service.ADDY_EXECUTOR_BINDING,
            "goal_id": "goal-test",
        },
    )


def _route(
    *,
    routing_id: str,
    provider: str = "nvidia_nim",
    model: str = "model-a",
) -> HarnessRoutingDecision:
    return HarnessRoutingDecision(
        routing_id=routing_id,
        intent="test",
        authorized_action="DEVELOPMENT",
        candidate_capability_ids=("ai.reasoning.text",),
        selected_capability_id="ai.reasoning.text",
        selected_provider=provider,
        selected_model=model,
        selected_executor_binding="ai.reasoning.text",
        selected_provider_executor_binding=(
            "app.services.harness_ai_provider_service."
            "execute_harness_ai_generation"
        ),
        primary_provider=provider,
        fallback_allowed=False,
        fallback_candidates=(),
        fallback_occurred=False,
        evidence_expectations=(),
        rationale=("test",),
        rejected_candidates=(),
        policy_metadata={},
    )


def _addy_route() -> HarnessRoutingDecision:
    return HarnessRoutingDecision(
        routing_id="addy-routing",
        intent="test addy",
        authorized_action="DEVELOPMENT",
        candidate_capability_ids=("addy:debugging-and-error-recovery",),
        selected_capability_id="addy:debugging-and-error-recovery",
        selected_provider=None,
        selected_model=None,
        selected_executor_binding=service.ADDY_EXECUTOR_BINDING,
        selected_provider_executor_binding=None,
        primary_provider=None,
        fallback_allowed=False,
        fallback_candidates=(),
        fallback_occurred=False,
        evidence_expectations=(),
        rationale=("test",),
        rejected_candidates=(),
        policy_metadata={},
    )


def _timeout(model: str, routing_id: str) -> HarnessAIProviderEvidence:
    return HarnessAIProviderEvidence(
        provider="nvidia_nim",
        status="FAILED",
        active=False,
        authority="deepseek_harness",
        authorized_action="DEVELOPMENT",
        harness_decision_id="decision-test",
        execution_id="execution-test",
        authorization_id="provider-auth",
        error={
            "code": "timeout",
            "retryable": True,
            "message": "NVIDIA NIM request timed out",
            "error_type": "TimeoutError",
            "failure_stage": "transport_request",
            "response_present": False,
            "structured_output_present": False,
            "parse_stage": "transport",
        },
        routing={"routing_id": routing_id},
        model=model,
        executor_binding="provider-executor",
        latency_seconds=54.0,
        retry_count=0,
        evidence_refs=(f"routing:{routing_id}",),
        performance={
            "total_attempt_latency_ms": 54000.0,
            "failure_class": "E_FULL_REQUEST_TIMEOUT",
            "response_present": False,
        },
    )


def _success(model: str, routing_id: str) -> HarnessAIProviderEvidence:
    return HarnessAIProviderEvidence(
        provider="nvidia_nim",
        status="EXECUTED",
        active=True,
        authority="deepseek_harness",
        authorized_action="DEVELOPMENT",
        harness_decision_id="decision-test",
        execution_id="execution-test",
        authorization_id="provider-auth",
        result={"text": "diagnosis complete"},
        routing={"routing_id": routing_id},
        model=model,
        executor_binding="provider-executor",
        latency_seconds=1.2,
        retry_count=0,
        evidence_refs=(f"routing:{routing_id}",),
        performance={"total_attempt_latency_ms": 1200.0},
    )


def _patch_common(monkeypatch):
    auth = _auth("capability:addy:debugging-and-error-recovery")
    provider_auth = _auth("provider:nvidia_nim")
    monkeypatch.setattr(
        service,
        "resolve_harness_authorization",
        lambda value: auth,
    )
    monkeypatch.setattr(
        service,
        "validate_harness_authorization",
        lambda value, **kwargs: auth,
    )
    monkeypatch.setattr(
        service,
        "issue_harness_authorization",
        lambda **kwargs: provider_auth,
    )
    monkeypatch.setattr(
        service,
        "consume_harness_authorization",
        lambda value: None,
    )
    monkeypatch.setattr(
        service,
        "resolve_pinned_addy_skill",
        lambda skill_name: ("trusted skill", "a" * 40, "b" * 64),
    )
    monkeypatch.setattr(
        service,
        "semantic_provider_health",
        lambda: {"eligible_zero_cost_provider_ids": ["nvidia_nim"]},
    )
    monkeypatch.setattr(
        service,
        "nvidia_semantic_planner_latency_budget",
        lambda: {"MODEL_ATTEMPT_DEADLINE_MS": 54000},
    )
    monkeypatch.setattr(
        service,
        "capture_canonical_execution_episode",
        lambda *args, **kwargs: {"episode_id": "episode-test"},
    )


def _payload():
    return {
        "mission_id": "mission-test",
        "task_id": "agent-diagnosis",
        "goal_id": "goal-test",
        "task_class": "debugging",
        "task": "Diagnose the observed production incident.",
        "context": {"evidence_refs": ["artifact:incident.json"]},
        "evidence_refs": ["artifact:incident.json"],
    }


def test_addy_timeout_replans_same_provider_to_alternate_model(monkeypatch):
    _patch_common(monkeypatch)
    route_a = _route(routing_id="routing-a", model="model-a")
    route_b = _route(routing_id="routing-b", model="model-b")
    route_requests = []

    def fake_route(request):
        route_requests.append(request)
        return route_a if len(route_requests) == 1 else route_b

    monkeypatch.setattr(service, "route_harness_request", fake_route)
    calls = iter([
        _timeout("model-a", "routing-a"),
        _timeout("model-a", "routing-a"),
        _success("model-b", "routing-b"),
    ])
    monkeypatch.setattr(
        service,
        "execute_harness_ai_generation",
        lambda **kwargs: next(calls),
    )

    result = service.execute_authorized_addy_skill(
        authorization=_auth(
            "capability:addy:debugging-and-error-recovery"
        ),
        routing_decision=_addy_route(),
        payload=_payload(),
    )

    assert result.status == "EXECUTED"
    assert result.active is True
    assert len(route_requests) == 2
    assert route_requests[1].preferred_providers == ("nvidia_nim",)
    assert route_requests[1].unavailable_model_ids == ("model-a",)
    assert route_requests[1].failure_pattern == (
        "transient_timeout_retry_exhausted"
    )
    assert route_requests[1].fallback_allowed is False
    assert result.result["same_routing_retry_count"] == 1
    assert result.result["same_routing_retry_result"] == "EXHAUSTED"
    assert result.result["transient_retry_exhausted"] is True
    assert result.result["localized_replan_attempted"] is True
    assert result.result["localized_replan_result"] == "RECOVERED"
    assert [row["phase"] for row in result.result["provider_attempts"]] == [
        "INITIAL",
        "SAME_ROUTING_RETRY",
        "LOCALIZED_MODEL_REPLAN",
    ]
    assert [row["provider"] for row in result.result["provider_attempts"]] == [
        "nvidia_nim",
        "nvidia_nim",
        "nvidia_nim",
    ]
    assert [row["model"] for row in result.result["provider_attempts"]] == [
        "model-a",
        "model-a",
        "model-b",
    ]


def test_addy_localized_replan_fails_closed_on_provider_drift(monkeypatch):
    _patch_common(monkeypatch)
    route_a = _route(routing_id="routing-a", model="model-a")
    route_drift = _route(
        routing_id="routing-b",
        provider="ollama_local",
        model="model-b",
    )
    route_requests = []

    def fake_route(request):
        route_requests.append(request)
        return route_a if len(route_requests) == 1 else route_drift

    monkeypatch.setattr(service, "route_harness_request", fake_route)
    calls = iter([
        _timeout("model-a", "routing-a"),
        _timeout("model-a", "routing-a"),
    ])
    monkeypatch.setattr(
        service,
        "execute_harness_ai_generation",
        lambda **kwargs: next(calls),
    )

    result = service.execute_authorized_addy_skill(
        authorization=_auth(
            "capability:addy:debugging-and-error-recovery"
        ),
        routing_decision=_addy_route(),
        payload=_payload(),
    )

    assert result.status == "FAILED"
    assert result.result["FAILURE_CLASS"] == "TRANSIENT_PROVIDER_TIMEOUT"
    assert result.result["TRANSIENT_RETRY_EXHAUSTED"] is True
    assert result.result["LOCALIZED_REPLAN_ATTEMPTED"] is True
    assert result.result["LOCALIZED_REPLAN_RESULT"] == "UNAVAILABLE"
    assert "escaped the original provider" in (
        result.result["LOCALIZED_REPLAN_ERROR"]
    )
    assert len(result.result["provider_attempts"]) == 2


def test_addy_nonretryable_failure_does_not_replan(monkeypatch):
    _patch_common(monkeypatch)
    route_a = _route(routing_id="routing-a", model="model-a")
    route_requests = []

    def fake_route(request):
        route_requests.append(request)
        return route_a

    monkeypatch.setattr(service, "route_harness_request", fake_route)
    failed = _timeout("model-a", "routing-a")
    failed = HarnessAIProviderEvidence(
        **{
            **failed.to_dict(),
            "error": {
                **failed.error,
                "code": "forbidden",
                "retryable": False,
                "failure_stage": "transport_response",
                "response_present": True,
            },
        }
    )
    monkeypatch.setattr(
        service,
        "execute_harness_ai_generation",
        lambda **kwargs: failed,
    )

    result = service.execute_authorized_addy_skill(
        authorization=_auth(
            "capability:addy:debugging-and-error-recovery"
        ),
        routing_decision=_addy_route(),
        payload=_payload(),
    )

    assert result.status == "FAILED"
    assert len(route_requests) == 1
    assert len(result.result["provider_attempts"]) == 1
    assert result.result["RETRY_COUNT"] == 0
    assert result.result["TRANSIENT_RETRY_EXHAUSTED"] is False
    assert result.result["LOCALIZED_REPLAN_ATTEMPTED"] is False
