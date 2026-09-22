import json
from unittest.mock import patch

import pytest

from app.database import harness_learning_repository as learning_repository
from app.database.schema import initialize_schema
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
from scripts import nvidia_multimodel_probe as nvidia_probe


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
            "live_status": "PASS",
            "http_status": 200,
            "latency_ms": 1000,
            "confidence": 0.9,
            "sample_size": 1,
            "rate_limit_state": "CLEAR",
            "quota_state": "AVAILABLE_UNMEASURED",
            "circuit_breaker_state": "CLOSED",
            "github_run_id": run_id,
            "evidence_refs": [
                f"github:run:{run_id}:nvidia-model:fixture"
            ],
        }
        for model_id in REQUIRED_MODELS
    }
    values["moonshotai/kimi-k3"].update({
        "availability": "DEGRADED",
        "live_status": "FAIL",
        "http_status": None,
        "failure_class": "timeout",
    })
    values["poolside/laguna-xs-2.1"].update({
        "availability": "DEGRADED",
        "live_status": "FAIL",
        "http_status": 503,
        "failure_class": "upstream_error",
    })
    values.update(overrides or {})
    return {"nvidia_nim": values}


@pytest.fixture(autouse=True)
def _existing_nvidia_secret_and_durable_health(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "nvidia-test-runtime")
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture-key")
    monkeypatch.setenv(
        "BR_NVIDIA_HEALTH_MAX_AGE_SECONDS",
        "315360000",
    )
    monkeypatch.delenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        raising=False,
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
            intent="fast structured agentic reasoning with tools",
            required_model_capabilities=(
                "fast_reasoning",
                "structured_output",
                "tool_use",
            ),
            tool_use_required=True,
            structured_output_required=True,
        )
    )
    assert decision.selected_provider == "nvidia_nim"
    assert (
        decision.selected_model
        == "nvidia/nemotron-3.5-lightning-30b-a3b"
    )
    assert "fast_reasoning" in decision.policy_metadata[
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
                "quota_state": "AVAILABLE_UNMEASURED",
                "circuit_breaker_state": "CLOSED",
                "github_run_id": "nvidia-test-runtime",
                "evidence_refs": [
                    "github:run:nvidia-test-runtime:nvidia-model:healthy"
                ],
            },
            "nvidia/nemotron-3.5-lightning-30b-a3b": {
                "availability": "DEGRADED",
                "failure_class": "synthetic_test_degraded",
                "latency_ms": 500,
                "confidence": 0.8,
                "sample_size": 1,
                "rate_limit_state": "CLEAR",
                "quota_state": "AVAILABLE_UNMEASURED",
                "circuit_breaker_state": "CLOSED",
                "github_run_id": "nvidia-test-runtime",
                "evidence_refs": [
                    "github:run:nvidia-test-runtime:nvidia-model:"
                    "lightning-degraded"
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

def test_nvidia_models_reuse_canonical_live_health_without_reprobe(
    monkeypatch,
):
    monkeypatch.delenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        raising=False,
    )

    expected = {
        "z-ai/glm-5.3": ("AVAILABLE", "PASS", 200),
        "nvidia/nemotron-3-ultra-550b-a55b": (
            "AVAILABLE",
            "PASS",
            200,
        ),
        "nvidia/nemotron-3.5-lightning-30b-a3b": (
            "AVAILABLE",
            "PASS",
            200,
        ),
        "moonshotai/kimi-k3": ("DEGRADED", "FAIL", None),
        "poolside/laguna-xs-2.1": ("DEGRADED", "FAIL", 503),
    }
    for model_id, (
        availability,
        live_status,
        http_status,
    ) in expected.items():
        observed = model_health("nvidia_nim", model_id)
        assert observed.availability == availability
        assert observed.live_status == live_status
        assert observed.http_status == http_status
        assert observed.source == "CANONICAL_LIVE_EVIDENCE"
        assert observed.last_verified_at
        assert observed.evidence_refs
        assert observed.quota_state == "AVAILABLE_UNMEASURED"

    decision = route_harness_request(
        _request(
            allowed_providers=("nvidia_nim",),
            required_model_capabilities=(
                "semantic_planning",
                "reasoning",
                "structured_output",
            ),
        )
    )
    assert decision.selected_model in {
        "z-ai/glm-5.3",
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3.5-lightning-30b-a3b",
    }


def test_three_proven_nvidia_models_are_selected_by_capability_not_task_id():
    classes = (
        (
            ("reasoning", "semantic_planning", "long_context"),
            "z-ai/glm-5.3",
        ),
        (
            ("fast_reasoning", "structured_output", "tool_use"),
            "nvidia/nemotron-3.5-lightning-30b-a3b",
        ),
        (
            ("complex_decision_support", "planning", "tool_use"),
            "nvidia/nemotron-3-ultra-550b-a55b",
        ),
    )
    selected = set()
    for capabilities, expected_model in classes:
        decision = route_harness_request(
            _request(
                allowed_providers=("nvidia_nim",),
                required_model_capabilities=capabilities,
                tool_use_required="tool_use" in capabilities,
                structured_output_required=(
                    "structured_output" in capabilities
                ),
            )
        )
        assert decision.selected_model == expected_model
        selected.add(decision.selected_model)

    assert len(selected) == 3
    assert {
        model_id
        for model_id in REQUIRED_MODELS
        if model_health(
            "nvidia_nim",
            model_id,
        ).availability == "AVAILABLE"
    } == selected


def test_quota_aware_routing_excludes_exhausted_model(monkeypatch):
    baseline = route_harness_request(
        _request(
            allowed_providers=("nvidia_nim",),
            required_model_capabilities=(
                "semantic_planning",
                "reasoning",
            ),
        )
    )
    exhausted = baseline.selected_model
    assert exhausted
    payload = _runtime_health_payload(overrides={
        exhausted: {
            "availability": "AVAILABLE",
            "live_status": "PASS",
            "http_status": 200,
            "latency_ms": 10,
            "confidence": 1.0,
            "sample_size": 1,
            "rate_limit_state": "CLEAR",
            "quota_state": "EXHAUSTED",
            "circuit_breaker_state": "CLOSED",
            "github_run_id": "nvidia-test-runtime",
            "evidence_refs": [
                "github:run:nvidia-test-runtime:nvidia-model:"
                "quota-exhausted"
            ],
        }
    })
    monkeypatch.setenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        json.dumps(payload),
    )
    decision = route_harness_request(
        _request(
            allowed_providers=("nvidia_nim",),
            required_model_capabilities=(
                "semantic_planning",
                "reasoning",
            ),
        )
    )
    assert decision.selected_model != exhausted
    assert any(
        "model_quota_state=EXHAUSTED"
        in rejection.reasons
        for rejection in decision.rejected_candidates
    )

def test_nvidia_probe_persists_structured_error_through_learning_plane(monkeypatch):
    initialize_schema()
    monkeypatch.setenv("GITHUB_RUN_ID", "nvidia-probe-persistence-test")
    record = _records()[0]
    result = {
        "MODEL_ID": record.model_id,
        "HTTP_STATUS": 429,
        "RESPONSE_VALID": False,
        "LATENCY_MS": 12.5,
        "TOOL_USE_SUPPORTED": False,
        "STRUCTURED_OUTPUT_RESULT": "FAIL",
        "TOKEN_USAGE_IF_AVAILABLE": {},
        "RATE_LIMIT_OBSERVED": True,
        "BILLING_CLASS": "NVIDIA_FREE_ENDPOINT",
        "HEALTH": "DEGRADED",
        "FAILURE_CLASS": "rate_limited",
    }
    nvidia_probe._persist(
        record,
        result,
        "2026-09-22T18:40:50+00:00",
        "2026-09-22T18:40:51+00:00",
    )
    model_hash = __import__("hashlib").sha256(
        str(record.model_id).encode("utf-8")
    ).hexdigest()[:16]
    persisted = learning_repository.get_episode(
        f"episode-nvidia-nvidia-probe-persistence-test-{model_hash}"
    )
    assert persisted is not None
    assert persisted["error"] == {
        "failure_class": "rate_limited",
        "http_status": 429,
    }

