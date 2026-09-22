import io
import json
from urllib import error
from unittest.mock import patch

import pytest

from app.services.ai_provider import AIProviderError
from app.services.harness_ai_provider_service import (
    HarnessAIProviderEvidence,
    select_harness_ai_provider,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.semantic_mission_planner_service import (
    SemanticPlannerProviderFailure,
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
