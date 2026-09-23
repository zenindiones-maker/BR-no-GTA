import io
import json
from urllib import error
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.ai_provider import AIProviderError
from app.services.harness_ai_provider_service import (
    HarnessAIProviderEvidence,
    select_harness_ai_provider,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.provider_health_service import model_health
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.semantic_mission_planner_service import (
    SemanticPlannerProviderFailure,
    _live_inference,
    _sanitized_provider_failure_evidence,
)
from app.services.tuxevil_ai_provider import TuxevilAIProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _responses_payload(text="BR PROVIDER OK"):
    return {
        "id": "resp-test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {
            "input_tokens": 11,
            "output_tokens": 4,
            "total_tokens": 15,
        },
    }


def _http_error(status, body):
    return error.HTTPError(
        "http://127.0.0.1:51200/v1/responses",
        status,
        "provider failure",
        None,
        io.BytesIO(body),
    )


def _runtime_health(monkeypatch, run_id="semantic-contract-1"):
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv(
        "BR_RUNTIME_PROVIDER_HEALTH_JSON",
        json.dumps(
            {
                "tuxevil": {
                    "provider_id": "tuxevil",
                    "state": "AVAILABLE",
                    "scope": "CURRENT_GITHUB_RUN",
                    "github_run_id": run_id,
                    "model_id": "gemini-3-flash",
                    "zero_cost_eligible": True,
                    "proof": {
                        "TUXEVIL_RESPONSES_API": "PASS",
                        "ANTIGRAVITY_UPSTREAM_AUTH": "PASS",
                        "TUXEVIL_LIVE_INFERENCE": "PASS",
                        "TUXEVIL_TOOL_CALLING": "PASS",
                        "OPENAI_PLATFORM_API_KEY_REQUIRED": "NO",
                    },
                    "evidence_refs": [
                        f"github:run:{run_id}:tuxevil-live-proof"
                    ],
                }
            }
        ),
    )


def test_semantic_planner_request_contract_uses_runtime_proven_responses(monkeypatch):
    monkeypatch.setenv("BR_CODEX_TUXEVIL_BASE_URL", "http://127.0.0.1:51200/v1")
    monkeypatch.setenv("BR_TUXEVIL_LOOPBACK_KEY", "loopback-test-key")
    provider = TuxevilAIProvider(model="gemini-3-flash", max_retries=0)

    with patch(
        "app.services.tuxevil_ai_provider.request.urlopen",
        return_value=FakeResponse(_responses_payload()),
    ) as mock_urlopen:
        response = provider.generate("Teste semantic planner")

    request_obj = mock_urlopen.call_args.args[0]
    body = json.loads(request_obj.data.decode("utf-8"))
    assert request_obj.full_url == "http://127.0.0.1:51200/v1/responses"
    assert request_obj.get_header("Authorization") == "Bearer loopback-test-key"
    assert body == {
        "model": "gemini-3-flash",
        "input": "Teste semantic planner",
        "store": False,
        "stream": False,
    }
    assert "messages" not in body
    assert response.text == "BR PROVIDER OK"
    assert response.usage.total_tokens == 15
    assert provider.transport == "tuxevil_responses"


def test_provider_error_classification_and_sanitized_diagnostics(monkeypatch):
    monkeypatch.setenv("BR_CODEX_TUXEVIL_BASE_URL", "http://127.0.0.1:51200/v1")
    provider = TuxevilAIProvider(model="gemini-3-flash", max_retries=0)
    leaked = b'{"error":{"message":"Bearer TOP-SECRET","code":"upstream_down"}}'

    with patch(
        "app.services.tuxevil_ai_provider.request.urlopen",
        side_effect=_http_error(503, leaked),
    ):
        with pytest.raises(AIProviderError) as captured:
            provider.generate("Teste")

    error_data = captured.value.to_dict()
    serialized = json.dumps(error_data, sort_keys=True)
    assert error_data["code"] == "http_error"
    assert error_data["status_code"] == 503
    assert error_data["retryable"] is True
    assert error_data["failure_stage"] == "transport_response"
    assert error_data["transport"] == "tuxevil_responses"
    assert error_data["response_present"] is True
    assert error_data["structured_output_present"] is True
    assert error_data["parse_stage"] == "http_status"
    assert error_data["error_type"] == "HTTPError"
    assert error_data["sanitized_reason"] == "http_503"
    assert "TOP-SECRET" not in serialized
    assert "Bearer" not in serialized


def test_retry_policy_is_single_bounded_retry(monkeypatch):
    monkeypatch.setenv("BR_CODEX_TUXEVIL_BASE_URL", "http://127.0.0.1:51200/v1")
    provider = TuxevilAIProvider(
        model="gemini-3-flash",
        max_retries=1,
        timeout=0.01,
    )
    transient = _http_error(503, b'{"error":{"code":"temporarily_unavailable"}}')

    with patch(
        "app.services.tuxevil_ai_provider.request.urlopen",
        side_effect=[transient, FakeResponse(_responses_payload("RECOVERED"))],
    ) as mock_urlopen:
        response = provider.generate("Teste")

    assert response.text == "RECOVERED"
    assert mock_urlopen.call_count == 2
    assert provider.last_retry_count == 1

    provider = TuxevilAIProvider(model="gemini-3-flash", max_retries=1)
    with patch(
        "app.services.tuxevil_ai_provider.request.urlopen",
        side_effect=[
            _http_error(503, b'{"error":{"code":"down"}}'),
            _http_error(503, b'{"error":{"code":"still_down"}}'),
        ],
    ) as mock_urlopen:
        with pytest.raises(AIProviderError):
            provider.generate("Teste")
    assert mock_urlopen.call_count == 2
    assert provider.last_retry_count == 1

    with pytest.raises(ValueError, match="0 or 1"):
        TuxevilAIProvider(max_retries=2)


def test_semantic_provider_failure_logs_safe_structured_diagnostics():
    evidence = HarnessAIProviderEvidence(
        provider="tuxevil",
        status="FAILED",
        active=False,
        authority="deepseek_harness",
        authorized_action="DECISION",
        harness_decision_id="routing-1",
        execution_id="execution-1",
        model="gemini-3-flash",
        executor_binding="app.services.ai_provider_factory.create_ai_provider",
        latency_seconds=3.2,
        retry_count=1,
        error={
            "code": "http_error",
            "status_code": 503,
            "retryable": True,
            "message": "Bearer SHOULD-NOT-LEAK",
            "error_type": "HTTPError",
            "failure_pattern": "tuxevil_http_503",
            "failure_stage": "transport_response",
            "transport": "tuxevil_responses",
            "response_present": True,
            "structured_output_present": True,
            "parse_stage": "http_status",
            "sanitized_reason": "http_503",
        },
        performance={"transport": "tuxevil_responses", "retry_count": 1},
    )
    sanitized = _sanitized_provider_failure_evidence(evidence)
    failure = SemanticPlannerProviderFailure("http_error", sanitized)
    rendered = str(failure)

    assert failure.diagnostics == {
        "provider_id": "tuxevil",
        "model_id": "gemini-3-flash",
        "transport": "tuxevil_responses",
        "failure_stage": "transport_response",
        "exception_class": "HTTPError",
        "http_status": 503,
        "retry_count": 1,
        "response_present": True,
        "structured_output_present": True,
        "parse_stage": "http_status",
        "sanitized_reason": "http_503",
    }
    assert "SHOULD-NOT-LEAK" not in rendered
    assert "Bearer" not in rendered
    assert "provider_id" in rendered
    assert "http_status" in rendered


def test_provider_health_route_consistency_uses_same_runtime_model_and_transport(
    monkeypatch,
):
    run_id = "semantic-route-2001"
    _runtime_health(monkeypatch, run_id)
    monkeypatch.setenv("BR_CODEX_TUXEVIL_BASE_URL", "http://127.0.0.1:51200/v1")
    monkeypatch.setenv("BR_TUXEVIL_LOOPBACK_KEY", "loopback-only")

    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="semantic mission planning proposal only",
            authorized_action="DECISION",
            domain="ai",
            goal_id="goal-semantic-route",
            task_class="semantic-mission-planning",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("tuxevil",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DECISION",
        subject="provider:tuxevil",
        harness_decision_id=decision.routing_id,
        execution_id="semantic-route-execution",
    )
    provider_name, provider = select_harness_ai_provider(
        provider_name="tuxevil",
        authorization=authorization,
        routing_decision=decision,
    )

    assert provider_name == "tuxevil"
    assert decision.selected_model == "gemini-3-flash"
    assert decision.policy_metadata["provider_model_binding_source"] == (
        "CURRENT_RUN_RUNTIME_PROOF"
    )
    assert provider.model == decision.selected_model
    assert provider.base_url == "http://127.0.0.1:51200/v1/responses"
    assert provider.transport == "tuxevil_responses"



def test_harness_routing_excludes_runtime_failed_nvidia_model(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    base = HarnessRoutingRequest(
        intent="semantic mission planning proposal only",
        authorized_action="DECISION",
        domain="ai",
        goal_id="goal-nvidia-model-reroute",
        task_class="semantic-mission-planning",
        required_capability_id="ai.reasoning.text",
        provider_required=True,
        preferred_providers=("nvidia_nim",),
        allowed_providers=("nvidia_nim",),
        required_model_capabilities=(
            "semantic_planning",
            "reasoning",
            "structured_output",
        ),
        structured_output_required=True,
        fallback_allowed=False,
        zero_cost_operation=True,
        learning_required=False,
    )
    first = route_harness_request(base)
    assert first.selected_provider == "nvidia_nim"
    assert first.selected_model

    second = route_harness_request(
        HarnessRoutingRequest(
            **{
                **base.__dict__,
                "unavailable_model_ids": (first.selected_model,),
            }
        )
    )
    assert second.selected_provider == "nvidia_nim"
    assert second.selected_model
    assert second.selected_model != first.selected_model
    assert first.selected_model in second.policy_metadata["unavailable_model_ids"]


def test_live_semantic_inference_reroutes_retryable_model_failure():
    route_one = SimpleNamespace(
        selected_provider="nvidia_nim",
        selected_model="model-a",
        routing_id="routing-a",
        to_dict=lambda: {
            "selected_provider": "nvidia_nim",
            "selected_model": "model-a",
            "routing_id": "routing-a",
        },
    )
    route_two = SimpleNamespace(
        selected_provider="nvidia_nim",
        selected_model="model-b",
        routing_id="routing-b",
        to_dict=lambda: {
            "selected_provider": "nvidia_nim",
            "selected_model": "model-b",
            "routing_id": "routing-b",
        },
    )
    failed = HarnessAIProviderEvidence(
        provider="nvidia_nim",
        status="FAILED",
        active=False,
        authority="DEEPSEEK_HARNESS",
        authorized_action="DECISION",
        harness_decision_id="routing-a",
        execution_id="execution-a",
        model="model-a",
        executor_binding="app.services.harness_ai_provider_service.execute_harness_ai_generation",
        latency_seconds=240.0,
        retry_count=1,
        error={
            "code": "timeout",
            "retryable": True,
            "failure_pattern": "nvidia_nim_timeout",
            "failure_stage": "transport_request",
            "transport": "nvidia_openai_chat_completions",
            "response_present": False,
            "structured_output_present": False,
            "parse_stage": "transport",
            "sanitized_reason": "timeout",
            "error_type": "TimeoutError",
        },
        performance={
            "transport": "nvidia_openai_chat_completions",
            "retry_count": 1,
        },
    )
    success = HarnessAIProviderEvidence(
        provider="nvidia_nim",
        status="EXECUTED",
        active=True,
        authority="DEEPSEEK_HARNESS",
        authorized_action="DECISION",
        harness_decision_id="routing-b",
        execution_id="execution-b",
        model="model-b",
        executor_binding="app.services.harness_ai_provider_service.execute_harness_ai_generation",
        latency_seconds=1.2,
        retry_count=0,
        result={
            "text": '{"ok":true}',
            "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            "finish_reason": "stop",
        },
        performance={
            "transport": "nvidia_openai_chat_completions",
            "retry_count": 0,
        },
    )
    requests = []

    def fake_route(request):
        requests.append(request)
        return route_one if len(requests) == 1 else route_two

    with patch(
        "app.services.harness_routing_policy_service.route_harness_request",
        side_effect=fake_route,
    ), patch(
        "app.services.harness_ai_provider_service.execute_harness_ai_generation",
        side_effect=[failed, success],
    ), patch(
        "app.services.harness_authorization_service.issue_harness_authorization",
        return_value=object(),
    ), patch(
        "app.services.harness_authorization_service.consume_harness_authorization",
    ), patch(
        "app.services.nvidia_model_learning_service."
        "record_nvidia_semantic_model_observation",
        return_value={"episode_id": "fixture"},
    ):
        text_value, evidence = _live_inference(
            "semantic prompt",
            {
                "goal_id": "goal-reroute",
                "provider_health": {
                    "eligible_zero_cost_provider_ids": ["nvidia_nim"]
                },
            },
        )

    assert text_value == '{"ok":true}'
    assert len(requests) == 2
    assert requests[1].preferred_providers == ("nvidia_nim",)
    assert requests[1].unavailable_model_ids == ("model-a",)
    assert requests[1].failure_pattern == "nvidia_nim_timeout"
    assert evidence["provider"] == "nvidia_nim"
    assert evidence["model"] == "model-b"
    assert evidence["routing"]["selected_model"] == "model-b"
    assert evidence["provider_reroute_count"] == 1
    assert evidence["model_call_count"] == 3
    assert [item["model"] for item in evidence["provider_attempts"]] == [
        "model-a",
        "model-b",
    ]



def test_nvidia_routing_uses_live_latency_before_capability_surplus(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    required = {"semantic_planning", "reasoning", "structured_output"}
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="semantic mission planning proposal only",
            authorized_action="DECISION",
            domain="ai",
            goal_id="goal-nvidia-latency-rank",
            task_class="semantic-mission-planning",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("nvidia_nim",),
            allowed_providers=("nvidia_nim",),
            prefer_low_latency=True,
            required_model_capabilities=tuple(sorted(required)),
            structured_output_required=True,
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        )
    )

    eligible = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.capability_type != "PROVIDER":
            continue
        if str(record.provider_id or "").lower().replace("-", "_") != "nvidia_nim":
            continue
        if not record.model_id or not record.available:
            continue
        capabilities = {
            tag.split(":", 1)[1]
            for tag in record.policy_tags
            if tag.startswith("model-capability:")
        }
        if not required.issubset(capabilities):
            continue
        health = model_health("nvidia_nim", record.model_id)
        if health.availability != "AVAILABLE" or health.latency_ms is None:
            continue
        eligible.append((float(health.latency_ms), record.model_id))

    assert len(eligible) >= 2
    minimum_latency = min(item[0] for item in eligible)
    selected_health = decision.policy_metadata["selected_model_health"]
    assert decision.selected_provider == "nvidia_nim"
    assert float(selected_health["latency_ms"]) == minimum_latency
