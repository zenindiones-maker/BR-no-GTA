import json
from unittest.mock import patch

import pytest

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    RoutingPolicyError,
    route_harness_request,
)
from app.services.nvidia_nim_provider import (
    DEFAULT_NVIDIA_NIM_BASE_URL,
    NvidiaNIMProvider,
    NvidiaNimProviderAdapter,
)
from app.services.provider_health_service import model_health


REQUIRED_MODELS = {
    "z-ai/glm-5.3",
    "moonshotai/kimi-k3",
    "nvidia/nemotron-3-ultra-550b-a55b",
    "poolside/laguna-xs-2.1",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
}


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _records():
    return [
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.capability_type == "PROVIDER"
        and record.provider_id == "nvidia_nim"
    ]


def _runtime_health_payload(*, overrides=None):
    run_id = "nvidia-test-runtime"
    values = {
        model_id: {
            "availability": "AVAILABLE",
            "latency_ms": 1000,
            "confidence": 0.9,
            "sample_size": 1,
            "rate_limit_state": "CLEAR",
            "circuit_breaker_state": "CLOSED",
            "github_run_id": run_id,
            "evidence_refs": [f"github:run:{run_id}:nvidia-model:fixture"],
        }
        for model_id in REQUIRED_MODELS
    }
    values.update(overrides or {})
    return {"nvidia_nim": values}


@pytest.fixture(autouse=True)
def _current_run_nvidia_health(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "nvidia-test-runtime")
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture-key")
    monkeypatch.setenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        json.dumps(_runtime_health_payload()),
    )


def _request(**kwargs):
    values = dict(
        intent="semantic planning reasoning structured output",
        authorized_action="DECISION",
        domain="ai",
        required_capability_id="ai.reasoning.text",
        provider_required=True,
        preferred_providers=("nvidia_nim",),
        fallback_allowed=False,
        zero_cost_operation=True,
        learning_required=False,
    )
    values.update(kwargs)
    return HarnessRoutingRequest(**values)


def test_nvidia_generic_adapter_and_multi_model_registry_contract():
    records = _records()
    assert {record.model_id for record in records} == REQUIRED_MODELS
    assert len({record.executor_binding for record in records}) == 1
    assert all(record.cost_class == "FREE_ENDPOINT" for record in records)
    assert all(
        "billing-mode:NVIDIA_FREE_ENDPOINT" in record.requirements
        for record in records
    )
    assert all(
        "paid-api-billing:NO" in record.requirements for record in records
    )
    assert all(
        "rate-limit-or-quota:POSSIBLE" in record.requirements
        for record in records
    )
    assert all(
        "unlimited:UNPROVEN" in record.requirements for record in records
    )
    assert NvidiaNIMProvider is NvidiaNimProviderAdapter
    assert DEFAULT_NVIDIA_NIM_BASE_URL == "https://integrate.api.nvidia.com/v1"


def test_adapter_accepts_dynamic_model_and_never_exposes_secret():
    model = "z-ai/glm-5.3"
    provider = NvidiaNimProviderAdapter(
        model=model,
        api_key="nvapi-SECRET-MUST-NOT-LEAK",
        max_retries=0,
    )
    payload = {
        "model": model,
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 2,
            "completion_tokens": 1,
            "total_tokens": 3,
        },
    }
    with patch(
        "app.services.nvidia_nim_provider.request.urlopen",
        return_value=FakeResponse(payload),
    ) as call:
        response = provider.generate("hello")

    req = call.call_args.args[0]
    body = json.loads(req.data.decode("utf-8"))
    assert req.full_url == (
        "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    assert body["model"] == model
    assert response.model == model
    safe = json.dumps(provider.safe_configuration(), sort_keys=True)
    assert "SECRET-MUST-NOT-LEAK" not in safe
    assert "nvapi-" not in safe


def test_capability_first_model_selection_is_not_task_hardcoded():
    decision = route_harness_request(
        _request(
            intent="agentic coding terminal implementation",
            required_model_capabilities=(
                "coding", "terminal", "agentic_coding"
            ),
        )
    )
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_model == "poolside/laguna-xs-2.1"
    assert "terminal" in decision.policy_metadata[
        "selected_model_capabilities"
    ]


def test_semantic_model_selection_comes_from_registry_capabilities():
    decision = route_harness_request(
        _request(
            required_model_capabilities=(
                "semantic_planning", "reasoning", "structured_output"
            ),
            structured_output_required=True,
        )
    )
    compatible = {
        record.model_id
        for record in _records()
        if {
            "model-capability:semantic_planning",
            "model-capability:reasoning",
            "model-capability:structured_output",
        }.issubset(set(record.policy_tags))
    }
    assert decision.selected_model in compatible
    assert decision.selected_model != "poolside/laguna-xs-2.1"


def test_model_level_circuit_breaker_excludes_only_failed_model(monkeypatch):
    baseline = route_harness_request(
        _request(
            required_model_capabilities=("semantic_planning", "reasoning")
        )
    )
    blocked = baseline.selected_model
    assert blocked
    monkeypatch.setenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        json.dumps(_runtime_health_payload(overrides={
            blocked: {
                "availability": "DEGRADED",
                "confidence": 1.0,
                "sample_size": 4,
                "rate_limit_state": "OBSERVED",
                "circuit_breaker_state": "OPEN",
                "failure_class": "rate_limited",
                "github_run_id": "nvidia-test-runtime",
                "evidence_refs": [
                    "github:run:nvidia-test-runtime:nvidia-model:circuit-open"
                ],
            }
        })),
    )
    decision = route_harness_request(
        _request(
            required_model_capabilities=("semantic_planning", "reasoning")
        )
    )
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_model != blocked
    assert any(
        "model_circuit_breaker_open" in rejection.reasons
        for rejection in decision.rejected_candidates
    )


def test_model_health_ranking_prefers_healthy_model(monkeypatch):
    degraded = "z-ai/glm-5.3"
    healthy = "nvidia/nemotron-3-ultra-550b-a55b"
    monkeypatch.setenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        json.dumps(_runtime_health_payload(overrides={
            degraded: {
                "availability": "DEGRADED",
                "failure_class": "upstream_error",
                "latency_ms": 9000,
                "confidence": 0.9,
                "sample_size": 3,
                "rate_limit_state": "UNKNOWN",
                "circuit_breaker_state": "CLOSED",
                "github_run_id": "nvidia-test-runtime",
                "evidence_refs": [
                    "github:run:nvidia-test-runtime:nvidia-model:degraded"
                ],
            },
            healthy: {
                "availability": "AVAILABLE",
                "latency_ms": 900,
                "confidence": 0.8,
                "sample_size": 2,
                "rate_limit_state": "CLEAR",
                "circuit_breaker_state": "CLOSED",
                "github_run_id": "nvidia-test-runtime",
                "evidence_refs": [
                    "github:run:nvidia-test-runtime:nvidia-model:healthy"
                ],
            },
        })),
    )
    decision = route_harness_request(
        _request(
            allowed_providers=("nvidia_nim",),
            required_model_capabilities=("semantic_planning", "reasoning"),
        )
    )
    assert decision.selected_model == healthy
    assert model_health(
        "nvidia_nim", degraded
    ).failure_class == "upstream_error"


def test_free_endpoint_remains_zero_cost_eligible():
    decision = route_harness_request(
        _request(
            required_model_capabilities=("semantic_planning", "reasoning")
        )
    )
    assert decision.policy_metadata[
        "selected_provider_cost_class"
    ] == "FREE_ENDPOINT"


def test_adapter_is_not_a_router_and_harness_keeps_authority():
    decision = route_harness_request(
        _request(
            required_model_capabilities=("semantic_planning", "reasoning")
        )
    )
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_provider_executor_binding == (
        "app.services.harness_ai_provider_service."
        "execute_harness_ai_generation"
    )
    assert not hasattr(NvidiaNimProviderAdapter, "route")
    assert not hasattr(NvidiaNimProviderAdapter, "select_model")
    assert decision.selected_model in REQUIRED_MODELS


def test_explicit_unhealthy_model_fails_closed_without_fallback(monkeypatch):
    model = "poolside/laguna-xs-2.1"
    monkeypatch.setenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        json.dumps(_runtime_health_payload(overrides={
            model: {
                "availability": "BLOCKED",
                "failure_class": "quota_exhausted",
                "confidence": 1.0,
                "sample_size": 2,
                "rate_limit_state": "OBSERVED",
                "circuit_breaker_state": "OPEN",
                "github_run_id": "nvidia-test-runtime",
                "evidence_refs": [
                    "github:run:nvidia-test-runtime:nvidia-model:quota-open"
                ],
            }
        })),
    )
    with pytest.raises(RoutingPolicyError):
        route_harness_request(
            _request(
                preferred_models=(model,),
                required_model_capabilities=("coding", "terminal"),
                fallback_allowed=False,
            )
        )

def test_nvidia_models_require_current_run_live_health_before_routing(monkeypatch):
    monkeypatch.delenv("BR_RUNTIME_MODEL_HEALTH_JSON", raising=False)
    with pytest.raises(RoutingPolicyError) as raised:
        route_harness_request(
            _request(
                allowed_providers=("nvidia_nim",),
                required_model_capabilities=("semantic_planning", "reasoning"),
            )
        )
    evidence = raised.value.evidence
    rejected = evidence.get("rejected_candidates") or []
    assert rejected
    assert any(
        any("model_live_runtime_proof_required" in reason for reason in item.get("reasons", ()))
        for item in rejected
    )
    assert model_health(
        "nvidia_nim", "z-ai/glm-5.3"
    ).availability == "UNKNOWN/UNPROVEN"

