from __future__ import annotations

from datetime import datetime, timezone
import json
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


def _upstream_failure(model: str, routing_id: str) -> HarnessAIProviderEvidence:
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
            "code": "upstream_error",
            "retryable": True,
            "message": "NVIDIA NIM upstream service failed",
            "error_type": "HTTPError",
            "failure_stage": "transport_response",
            "response_present": True,
            "structured_output_present": None,
            "parse_stage": "http_status",
            "status_code": 503,
        },
        routing={"routing_id": routing_id},
        model=model,
        executor_binding="provider-executor",
        latency_seconds=0.4,
        retry_count=0,
        evidence_refs=(f"routing:{routing_id}",),
        performance={
            "total_attempt_latency_ms": 400.0,
            "failure_class": "C_HTTP_5XX",
            "response_present": True,
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
        "full_timeout_same_model_retry_forbidden"
    )
    assert route_requests[1].fallback_allowed is False
    assert result.result["same_routing_retry_count"] == 0
    assert result.result["same_routing_retry_result"] == "NOT_APPLICABLE"
    assert result.result["transient_retry_exhausted"] is True
    assert result.result["same_model_full_timeout_retry_avoided"] is True
    assert result.result["localized_replan_attempted"] is True
    assert result.result["localized_replan_result"] == "RECOVERED"
    assert [row["phase"] for row in result.result["provider_attempts"]] == [
        "INITIAL",
        "LOCALIZED_MODEL_REPLAN",
    ]
    assert [row["provider"] for row in result.result["provider_attempts"]] == [
        "nvidia_nim",
        "nvidia_nim",
    ]
    assert [row["model"] for row in result.result["provider_attempts"]] == [
        "model-a",
        "model-b",
    ]


def test_addy_retryable_upstream_error_replans_same_provider_model(monkeypatch):
    _patch_common(monkeypatch)
    route_a = _route(routing_id="routing-upstream-a", model="model-a")
    route_b = _route(routing_id="routing-upstream-b", model="model-b")
    route_requests = []

    def fake_route(request):
        route_requests.append(request)
        return route_a if len(route_requests) == 1 else route_b

    monkeypatch.setattr(service, "route_harness_request", fake_route)
    calls = iter([
        _upstream_failure("model-a", "routing-upstream-a"),
        _upstream_failure("model-a", "routing-upstream-a"),
        _success("model-b", "routing-upstream-b"),
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
    assert len(route_requests) == 2
    assert route_requests[1].preferred_providers == ("nvidia_nim",)
    assert route_requests[1].unavailable_model_ids == ("model-a",)
    assert route_requests[1].failure_pattern == (
        "retryable_upstream_error_exhausted"
    )
    assert route_requests[1].fallback_allowed is False
    assert result.result["same_routing_retry_count"] == 1
    assert result.result["same_routing_retry_result"] == "EXHAUSTED"
    assert result.result["transient_retry_exhausted"] is False
    assert result.result["localized_replan_attempted"] is True
    assert result.result["localized_replan_result"] == "RECOVERED"
    assert result.result["localized_replan_failure_pattern"] == (
        "retryable_upstream_error_exhausted"
    )
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
    assert len(result.result["provider_attempts"]) == 1


def test_addy_read_stall_skips_same_model_retry(monkeypatch):
    _patch_common(monkeypatch)
    route_a = _route(routing_id="routing-read-a", model="model-a")
    route_b = _route(routing_id="routing-read-b", model="model-b")
    route_requests = []

    def fake_route(request):
        route_requests.append(request)
        return route_a if len(route_requests) == 1 else route_b

    stalled = _timeout("model-a", "routing-read-a")
    stalled = HarnessAIProviderEvidence(
        **{
            **stalled.to_dict(),
            "error": {
                **stalled.error,
                "failure_stage": "response_read",
                "response_present": True,
            },
        }
    )
    calls = iter([
        stalled,
        _success("model-b", "routing-read-b"),
    ])
    monkeypatch.setattr(service, "route_harness_request", fake_route)
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
    assert result.result["same_routing_retry_count"] == 0
    assert result.result["same_model_full_timeout_retry_avoided"] is True
    assert [row["phase"] for row in result.result["provider_attempts"]] == [
        "INITIAL",
        "LOCALIZED_MODEL_REPLAN",
    ]


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


def test_addy_correction_turn_uses_harness_structured_output_schema(monkeypatch):
    _patch_common(monkeypatch)
    route = _route(routing_id="routing-structured", model="model-a")
    route_requests = []
    generation_calls = []

    def fake_route(request):
        route_requests.append(request)
        return route

    def fake_generation(**kwargs):
        generation_calls.append(kwargs)
        return HarnessAIProviderEvidence(
            provider="nvidia_nim",
            status="EXECUTED",
            active=True,
            authority="deepseek_harness",
            authorized_action="DEVELOPMENT",
            harness_decision_id="decision-test",
            execution_id="execution-test",
            authorization_id="provider-auth",
            result={
                "text": (
                    '{"schema":"IncidentDiagnosisEvidence",'
                    '"failure_class":"REGISTRY_SELECTION_FAILURE",'
                    '"observed_evidence":["artifact:incident.json"],'
                    '"localization":"Registry selection",'
                    '"confidence":0.9,'
                    '"evidence_refs":["artifact:incident.json"]}'
                )
            },
            routing={"routing_id": "routing-structured"},
            model="model-a",
            executor_binding="provider-executor",
            latency_seconds=0.2,
            retry_count=0,
            evidence_refs=("routing:routing-structured",),
            performance={
                "structured_output_mode": "json_schema",
                "total_attempt_latency_ms": 200.0,
            },
        )

    monkeypatch.setattr(service, "route_harness_request", fake_route)
    monkeypatch.setattr(
        service,
        "execute_harness_ai_generation",
        fake_generation,
    )
    payload = _payload()
    payload["functional_role"] = "DIAGNOSIS"
    payload["context"] = {
        "evidence_refs": ["artifact:incident.json"],
        "output_validation_feedback": {
            "schema": "TaskOutputValidationFeedback/v1",
            "expected_schema": "IncidentDiagnosisEvidence",
            "errors": ["FINAL_STRUCTURED_OUTPUT_MISSING"],
        },
    }

    result = service.execute_authorized_addy_skill(
        authorization=_auth(
            "capability:addy:debugging-and-error-recovery"
        ),
        routing_decision=_addy_route(),
        payload=payload,
    )

    assert result.status == "EXECUTED"
    assert route_requests[0].structured_output_required is True
    schema = generation_calls[0]["structured_output_schema"]
    assert schema["properties"]["schema"]["const"] == (
        "IncidentDiagnosisEvidence"
    )
    assert "schema" in schema["required"]
    assert result.result["structured_output_enforced"] is True
    assert result.result["structured_output_schema"] == (
        "IncidentDiagnosisEvidence"
    )


def test_addy_tool_request_correction_uses_harness_tool_schema(monkeypatch):
    _patch_common(monkeypatch)
    route = _route(routing_id="routing-tool-structured", model="model-a")
    route_requests = []
    generation_calls = []

    def fake_route(request):
        route_requests.append(request)
        return route

    def fake_generation(**kwargs):
        generation_calls.append(kwargs)
        return HarnessAIProviderEvidence(
            provider="nvidia_nim",
            status="EXECUTED",
            active=True,
            authority="deepseek_harness",
            authorized_action="DEVELOPMENT",
            harness_decision_id="decision-test",
            execution_id="execution-test",
            authorization_id="provider-auth",
            result={
                "text": (
                    '{"schema":"ToolRequestEnvelope/v1",'
                    '"request_id":"req-corrected",'
                    '"mission_id":"mission-test",'
                    '"task_id":"task-test",'
                    '"agent_id":"addy-agent-skills",'
                    '"capability_id":"addy:debugging-and-error-recovery",'
                    '"tool_or_capability_id":"artifact.evidence.reuse",'
                    '"operation":"EXECUTE_CAPABILITY",'
                    '"arguments":{},'
                    '"input_refs":["artifact:incident.json"],'
                    '"reason":"Read observed evidence",'
                    '"authorization_context":{"authority":"DEEPSEEK_HARNESS"}}'
                )
            },
            routing={"routing_id": "routing-tool-structured"},
            model="model-a",
            executor_binding="provider-executor",
            latency_seconds=0.2,
            retry_count=0,
            evidence_refs=("routing:routing-tool-structured",),
            performance={
                "structured_output_mode": "json_schema",
                "total_attempt_latency_ms": 200.0,
            },
        )

    monkeypatch.setattr(service, "route_harness_request", fake_route)
    monkeypatch.setattr(
        service,
        "execute_harness_ai_generation",
        fake_generation,
    )
    payload = _payload()
    payload["functional_role"] = "ROOT_CAUSE"
    payload["agent_tool_capabilities"] = ["artifact.evidence.reuse"]
    payload["context"] = {
        "evidence_refs": ["artifact:incident.json"],
        "output_validation_feedback": {
            "schema": "ToolRequestValidationFeedback/v1",
            "expected_schema": "ToolRequestEnvelope/v1",
            "errors": ["TOOL_REQUEST_REASON_REQUIRED"],
        },
    }

    result = service.execute_authorized_addy_skill(
        authorization=_auth(
            "capability:addy:debugging-and-error-recovery"
        ),
        routing_decision=_addy_route(),
        payload=payload,
    )

    assert result.status == "EXECUTED"
    assert route_requests[0].structured_output_required is True
    schema = generation_calls[0]["structured_output_schema"]
    assert schema["properties"]["schema"]["const"] == (
        "ToolRequestEnvelope/v1"
    )
    assert schema["properties"]["tool_or_capability_id"]["enum"] == [
        "artifact.evidence.reuse"
    ]
    assert schema["properties"]["reason"]["minLength"] == 1
    assert "reason" in schema["required"]
    assert result.result["structured_output_enforced"] is True
    assert result.result["structured_output_schema"] == (
        "ToolRequestEnvelope/v1"
    )



def test_addy_first_semantic_turn_uses_agent_turn_schema(monkeypatch):
    _patch_common(monkeypatch)
    route = _route(routing_id="routing-agent-turn", model="model-a")
    route_requests = []
    generation_calls = []

    def fake_route(request):
        route_requests.append(request)
        return route

    def fake_generation(**kwargs):
        generation_calls.append(kwargs)
        return HarnessAIProviderEvidence(
            provider="nvidia_nim",
            status="EXECUTED",
            active=True,
            authority="deepseek_harness",
            authorized_action="DEVELOPMENT",
            harness_decision_id="decision-test",
            execution_id="execution-test",
            authorization_id="provider-auth",
            result={
                "text": json.dumps({
                    "schema": "AgentTurnEnvelope/v1",
                    "kind": "FINAL_OUTPUT",
                    "tool_request": None,
                    "final_output": {
                        "schema": "IncidentDiagnosisEvidence",
                        "failure_class": "REGISTRY_SELECTION_FAILURE",
                        "observed_evidence": ["artifact:incident.json"],
                        "localization": "Registry selection",
                        "confidence": 0.9,
                        "evidence_refs": ["artifact:incident.json"],
                    },
                })
            },
            routing={"routing_id": "routing-agent-turn"},
            model="model-a",
            executor_binding="provider-executor",
            latency_seconds=0.2,
            retry_count=0,
            evidence_refs=("routing:routing-agent-turn",),
            performance={
                "structured_output_mode": "json_schema",
                "total_attempt_latency_ms": 200.0,
            },
        )

    monkeypatch.setattr(service, "route_harness_request", fake_route)
    monkeypatch.setattr(
        service,
        "execute_harness_ai_generation",
        fake_generation,
    )
    payload = _payload()
    payload["functional_role"] = "DIAGNOSIS"
    payload["agent_turn_schema"] = "AgentTurnEnvelope/v1"
    payload["agent_tool_capabilities"] = ["artifact.evidence.reuse"]

    result = service.execute_authorized_addy_skill(
        authorization=_auth(
            "capability:addy:debugging-and-error-recovery"
        ),
        routing_decision=_addy_route(),
        payload=payload,
    )

    assert result.status == "EXECUTED"
    assert route_requests[0].structured_output_required is True
    schema = generation_calls[0]["structured_output_schema"]
    assert schema["properties"]["schema"]["const"] == "AgentTurnEnvelope/v1"
    assert len(schema["oneOf"]) == 2
    assert result.result["structured_output_enforced"] is True
    assert result.result["structured_output_schema"] == "AgentTurnEnvelope/v1"



def test_external_localized_replan_excludes_exhausted_model(monkeypatch):
    _patch_common(monkeypatch)
    route_b = _route(routing_id="routing-b", model="model-b")
    route_requests = []
    generation_calls = []

    def fake_route(request):
        route_requests.append(request)
        return route_b

    def fake_generation(**kwargs):
        generation_calls.append(kwargs)
        return _success("model-b", "routing-b")

    monkeypatch.setattr(service, "route_harness_request", fake_route)
    monkeypatch.setattr(
        service,
        "execute_harness_ai_generation",
        fake_generation,
    )
    payload = _payload()
    payload["context"]["internal_recovery"] = {
        "RECOVERY_STRATEGY": "LOCALIZED_PROVIDER_REPLAN",
        "PREVIOUS_SELECTED_PROVIDER": "nvidia_nim",
        "PREVIOUS_SELECTED_MODEL": "model-a",
        "ATTEMPTED_ROUTING_IDS": ["routing-a"],
        "ATTEMPTED_PROVIDER_MODEL_PAIRS": [{
            "provider_id": "nvidia_nim",
            "model_id": "model-a",
            "routing_id": "routing-a",
            "attempt_id": "attempt-a",
            "failure_class": "TRANSIENT_PROVIDER_TIMEOUT",
        }],
        "EXHAUSTED_PROVIDER_MODEL_PAIRS": [{
            "provider_id": "nvidia_nim",
            "model_id": "model-a",
            "routing_id": "routing-a",
            "attempt_id": "attempt-a",
            "failure_class": "TRANSIENT_PROVIDER_TIMEOUT",
        }],
        "SAME_MODEL_FULL_TIMEOUT_RETRY": "FORBIDDEN",
    }

    result = service.execute_authorized_addy_skill(
        authorization=_auth(
            "capability:addy:debugging-and-error-recovery"
        ),
        routing_decision=_addy_route(),
        payload=payload,
    )

    assert len(route_requests) == 1
    assert route_requests[0].preferred_providers == ("nvidia_nim",)
    assert route_requests[0].unavailable_model_ids == ("model-a",)
    assert route_requests[0].exhausted_provider_model_pairs == (
        ("nvidia_nim", "model-a"),
    )
    assert route_requests[0].failure_pattern == (
        "external_localized_provider_replan"
    )
    assert len(generation_calls) == 1
    assert result.status == "EXECUTED"
    assert result.result["SELECTED_RECOVERY_PROVIDER"] == "nvidia_nim"
    assert result.result["SELECTED_RECOVERY_MODEL"] == "model-b"
    assert result.result["RECOVERY_ROUTE_CHANGED"] is True
    assert result.result["IDENTICAL_ROUTE_RETRY_COUNT"] == 0
    assert result.result["BOUNDED_PROVIDER_ATTEMPTS"] is True
    pairs = {
        (item["provider_id"], item["model_id"])
        for item in result.result["ATTEMPTED_PROVIDER_MODEL_PAIRS"]
    }
    assert pairs == {
        ("nvidia_nim", "model-a"),
        ("nvidia_nim", "model-b"),
    }


def test_external_localized_replan_rejects_identical_route(monkeypatch):
    _patch_common(monkeypatch)
    route_b_same_route = _route(
        routing_id="routing-a",
        model="model-b",
    )
    generation_calls = []
    monkeypatch.setattr(
        service,
        "route_harness_request",
        lambda request: route_b_same_route,
    )
    monkeypatch.setattr(
        service,
        "execute_harness_ai_generation",
        lambda **kwargs: generation_calls.append(kwargs),
    )
    payload = _payload()
    payload["context"]["internal_recovery"] = {
        "RECOVERY_STRATEGY": "LOCALIZED_PROVIDER_REPLAN",
        "PREVIOUS_SELECTED_PROVIDER": "nvidia_nim",
        "ATTEMPTED_ROUTING_IDS": ["routing-a"],
        "ATTEMPTED_PROVIDER_MODEL_PAIRS": [{
            "provider_id": "nvidia_nim",
            "model_id": "model-a",
            "routing_id": "routing-a",
        }],
        "EXHAUSTED_PROVIDER_MODEL_PAIRS": [{
            "provider_id": "nvidia_nim",
            "model_id": "model-a",
            "routing_id": "routing-a",
        }],
    }

    with pytest.raises(
        PermissionError,
        match="IDENTICAL_ROUTE_AFTER_LOCALIZED_REPLAN_FORBIDDEN",
    ):
        service.execute_authorized_addy_skill(
            authorization=_auth(
                "capability:addy:debugging-and-error-recovery"
            ),
            routing_decision=_addy_route(),
            payload=payload,
        )
    assert generation_calls == []


def test_failed_provider_attempt_persists_failed_episode(monkeypatch):
    _patch_common(monkeypatch)
    route_a = _route(routing_id="routing-a", model="model-a")
    route_b = _route(routing_id="routing-b", model="model-b")
    routes = iter([route_a, route_b])
    monkeypatch.setattr(
        service,
        "route_harness_request",
        lambda request: next(routes),
    )
    calls = iter([
        _timeout("model-a", "routing-a"),
        _timeout("model-b", "routing-b"),
    ])
    monkeypatch.setattr(
        service,
        "execute_harness_ai_generation",
        lambda **kwargs: next(calls),
    )
    episodes = []
    monkeypatch.setattr(
        service,
        "capture_canonical_execution_episode",
        lambda canonical, **kwargs: episodes.append(canonical) or {
            "episode_id": "failed-episode"
        },
    )

    result = service.execute_authorized_addy_skill(
        authorization=_auth(
            "capability:addy:debugging-and-error-recovery"
        ),
        routing_decision=_addy_route(),
        payload=_payload(),
    )

    assert result.status == "FAILED"
    assert result.result["BOUNDED_PROVIDER_ATTEMPTS"] is True
    assert len(result.result["EXHAUSTED_PROVIDER_MODEL_PAIRS"]) == 2
    assert len(episodes) == 1
    assert episodes[0].success is False
    assert episodes[0].status == "FAILED"
