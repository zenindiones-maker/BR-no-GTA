import json

import pytest
from dataclasses import replace

from app.services.ai_provider import AIProviderError, AIResponse, AIUsage
from app.services.global_capability_registry import (
    AVAILABLE,
    FUNCTIONAL,
    GLOBAL_CAPABILITY_REGISTRY,
    GlobalCapabilityRegistry,
)
from app.services.harness_ai_provider_service import (
    ResilientHarnessAIProvider,
    execute_harness_ai_generation,
    select_harness_ai_provider,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingDecision,
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services import provider_health_service as provider_health_module
from app.services.harness_authorization_service import issue_harness_authorization


def auth(provider="nvidia_nim"):
    return issue_harness_authorization(authorized_action="EDITORIAL", subject=f"provider:{provider}", harness_decision_id="decision-1", execution_id="execution-1")


def _install_free_test_provider(monkeypatch, provider_id, *, model_id=None):
    import app.services.harness_ai_provider_service as ai_service
    import app.services.harness_routing_policy_service as routing_service

    if provider_id == "nvidia_nim":
        runtime_model = (
            model_id
            or "nvidia/nemotron-3.5-lightning-30b-a3b"
        )
        run_id = "nvidia-ai-provider-test-runtime"
        monkeypatch.setenv("GITHUB_RUN_ID", run_id)
        monkeypatch.setenv("NVIDIA_API_KEY", "fixture-key")
        monkeypatch.setenv(
            "BR_RUNTIME_MODEL_HEALTH_JSON",
            json.dumps({
                "nvidia_nim": {
                    runtime_model: {
                        "availability": "AVAILABLE",
                        "latency_ms": 1000,
                        "confidence": 0.95,
                        "sample_size": 1,
                        "rate_limit_state": "CLEAR",
                        "circuit_breaker_state": "CLOSED",
                        "github_run_id": run_id,
                        "evidence_refs": [
                            f"github:run:{run_id}:nvidia-model:fixture"
                        ],
                    }
                }
            }),
        )

    records = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.provider_id == provider_id:
            changes = {
                "availability": AVAILABLE,
                "maturity": FUNCTIONAL,
                "cost_class": "FREE_NO_BILLING",
            }
            if model_id is not None:
                changes["model_id"] = model_id
            record = replace(record, **changes)
        records.append(record)

    registry = GlobalCapabilityRegistry(records)
    monkeypatch.setattr(ai_service, "GLOBAL_CAPABILITY_REGISTRY", registry)
    monkeypatch.setattr(routing_service, "GLOBAL_CAPABILITY_REGISTRY", registry)
    monkeypatch.setattr(
        ai_service,
        "route_harness_request",
        lambda request: routing_service.route_harness_request(
            request,
            registry=registry,
        ),
    )
    return registry


class FakeProvider:
    def generate(self, prompt):
        assert prompt == "Teste"
        return AIResponse(text="OK", provider="nvidia_nim", model="nvidia/nemotron-3-super-120b-a12b", reasoning_content="reasoning", usage=AIUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3), finish_reason="stop")


def test_harness_boundary_returns_normalized_lineage_evidence(monkeypatch):
    _install_free_test_provider(
        monkeypatch,
        "nvidia_nim",
        model_id="nvidia/nemotron-3-super-120b-a12b",
    )
    authorization = auth()
    def selector(*, provider_name, authorization):
        assert provider_name == "nvidia"
        assert authorization.authority == "deepseek_harness"
        return "nvidia_nim", FakeProvider()
    evidence = execute_harness_ai_generation(provider_name="nvidia", prompt="Teste", authorization=authorization, selector=selector)
    assert evidence.status == "EXECUTED"
    assert evidence.provider == "nvidia_nim"
    assert evidence.authority == "deepseek_harness"
    assert evidence.result["usage"]["total_tokens"] == 3
    assert evidence.routing["selected_model"] == "nvidia/nemotron-3-super-120b-a12b"


def test_fabricated_authorization_is_rejected_before_provider_selection():
    with pytest.raises(PermissionError, match="not found"):
        select_harness_ai_provider(provider_name="nvidia", authorization="fabricated")


def test_nvidia_selection_is_lazy_policy_owned_and_model_bound(monkeypatch):
    _install_free_test_provider(
        monkeypatch,
        "nvidia_nim",
        model_id="nvidia/nemotron-3-super-120b-a12b",
    )
    import app.services.harness_ai_provider_service as service
    calls = []
    class SelectedProvider: pass
    def construct(**kwargs):
        calls.append(kwargs)
        return SelectedProvider()
    monkeypatch.setattr(service, "NvidiaNIMProvider", construct)
    provider_name, provider = service.select_harness_ai_provider(provider_name="nvidia", authorization=auth())
    assert provider_name == "nvidia_nim" and isinstance(provider, SelectedProvider)
    assert calls == [{"model": "nvidia/nemotron-3-super-120b-a12b"}]


def test_nvidia_selection_accepts_per_call_bounded_timeout(monkeypatch):
    _install_free_test_provider(
        monkeypatch,
        "nvidia_nim",
        model_id="nvidia/nemotron-3-super-120b-a12b",
    )
    import app.services.harness_ai_provider_service as service

    calls = []

    class SelectedProvider:
        pass

    def construct(**kwargs):
        calls.append(kwargs)
        return SelectedProvider()

    monkeypatch.setattr(service, "NvidiaNIMProvider", construct)
    provider_name, provider = service.select_harness_ai_provider(
        provider_name="nvidia_nim",
        authorization=auth(),
        request_timeout_seconds=17.5,
    )
    assert provider_name == "nvidia_nim"
    assert isinstance(provider, SelectedProvider)
    assert calls == [{
        "model": "nvidia/nemotron-3-super-120b-a12b",
        "timeout_seconds": 17.5,
    }]


def test_tuxevil_selection_requires_governed_concrete_model(monkeypatch):
    _install_free_test_provider(monkeypatch, "tuxevil")
    import app.services.harness_ai_provider_service as service

    monkeypatch.setattr(
        service,
        "NvidiaNIMProvider",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("NVIDIA must not be touched")
        ),
    )

    with pytest.raises(
        PermissionError,
        match="requires an explicit selected model",
    ):
        service.select_harness_ai_provider(
            provider_name="tuxevil",
            authorization=auth("tuxevil"),
        )


def test_tuxevil_unregistered_concrete_model_is_rejected(monkeypatch):
    import app.services.harness_ai_provider_service as service

    selected_model = "unproven-tuxevil-model"

    monkeypatch.setattr(
        service,
        "NvidiaNIMProvider",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("NVIDIA must not be touched")
        ),
    )

    decision = HarnessRoutingDecision(
        routing_id="routing-tuxevil-unproven-model",
        intent="ai reasoning text provider selection",
        authorized_action="EDITORIAL",
        candidate_capability_ids=("ai.reasoning.text",),
        selected_capability_id="ai.reasoning.text",
        selected_provider="tuxevil",
        selected_model=selected_model,
        selected_executor_binding="harness_ai_provider_service",
        selected_provider_executor_binding=(
            "app.services.ai_provider_factory.create_ai_provider"
        ),
        primary_provider="tuxevil",
        fallback_allowed=False,
        fallback_candidates=(),
        fallback_occurred=False,
        evidence_expectations=("HarnessAIProviderEvidence",),
        rationale=("unproven model must fail closed",),
        rejected_candidates=(),
        policy_metadata={},
    )

    with pytest.raises(
        PermissionError,
        match="model does not match Registry metadata",
    ):
        service.select_harness_ai_provider(
            provider_name="tuxevil",
            authorization=auth("tuxevil"),
            routing_decision=decision,
        )


def test_static_registry_provider_model_matches_end_to_end(monkeypatch):
    registry = _install_free_test_provider(
        monkeypatch,
        "nvidia_nim",
        model_id="nvidia/nemotron-3-super-120b-a12b",
    )
    import app.services.harness_ai_provider_service as service

    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="static model contract",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("nvidia_nim",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        ),
        registry=registry,
    )
    assert decision.selected_model == "nvidia/nemotron-3-super-120b-a12b"
    assert decision.policy_metadata["provider_model_binding_source"] == "REGISTRY_STATIC"

    calls = []
    class RuntimeProvider:
        pass

    monkeypatch.setattr(
        service,
        "NvidiaNIMProvider",
        lambda *, model=None: calls.append(model) or RuntimeProvider(),
    )
    provider_name, provider = service.select_harness_ai_provider(
        provider_name="nvidia_nim",
        authorization=auth("nvidia_nim"),
        routing_decision=decision,
    )
    assert provider_name == "nvidia_nim"
    assert isinstance(provider, RuntimeProvider)
    assert calls == ["nvidia/nemotron-3-super-120b-a12b"]


def test_correct_provider_with_divergent_model_is_blocked(monkeypatch):
    registry = _install_free_test_provider(
        monkeypatch,
        "nvidia_nim",
        model_id="nvidia/nemotron-3-super-120b-a12b",
    )
    import app.services.harness_ai_provider_service as service

    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="static model contract",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("nvidia_nim",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        ),
        registry=registry,
    )
    divergent = replace(decision, selected_model="other-model")
    with pytest.raises(
        PermissionError,
        match="model does not match Registry metadata",
    ):
        service.select_harness_ai_provider(
            provider_name="nvidia_nim",
            authorization=auth("nvidia_nim"),
            routing_decision=divergent,
        )


def test_runtime_overlay_cannot_invent_model_outside_static_registry_contract(
    monkeypatch,
):
    registry = _install_free_test_provider(
        monkeypatch,
        "nvidia_nim",
        model_id="nvidia/nemotron-3-super-120b-a12b",
    )
    run_id = "2000"
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        json.dumps({
            "nvidia_nim": {
                "nvidia/nemotron-3-super-120b-a12b": {
                    "availability": "AVAILABLE",
                    "latency_ms": 1000,
                    "confidence": 0.95,
                    "sample_size": 1,
                    "rate_limit_state": "CLEAR",
                    "circuit_breaker_state": "CLOSED",
                    "github_run_id": run_id,
                    "evidence_refs": [
                        f"github:run:{run_id}:nvidia-model:static-contract"
                    ],
                }
            }
        }),
    )
    monkeypatch.setenv(
        "BR_RUNTIME_PROVIDER_HEALTH_JSON",
        json.dumps({
            "nvidia_nim": {
                "provider_id": "nvidia_nim",
                "state": "AVAILABLE",
                "scope": "CURRENT_GITHUB_RUN",
                "github_run_id": run_id,
                "model_id": "invented-runtime-model",
                "zero_cost_eligible": True,
                "proof": {
                    "TUXEVIL_RESPONSES_API": "PASS",
                    "ANTIGRAVITY_UPSTREAM_AUTH": "PASS",
                    "TUXEVIL_LIVE_INFERENCE": "PASS",
                    "TUXEVIL_TOOL_CALLING": "PASS",
                    "OPENAI_PLATFORM_API_KEY_REQUIRED": "NO",
                },
                "evidence_refs": [
                    f"github:run:{run_id}:runtime-provider-proof"
                ],
            }
        }),
    )
    record = next(
        item
        for item in registry.all()
        if item.provider_id == "nvidia_nim"
    )
    binding = provider_health_module.authorized_provider_model_binding(record)
    assert binding is not None
    assert binding["source"] == "REGISTRY_STATIC"
    assert binding["model_id"] == "nvidia/nemotron-3-super-120b-a12b"

    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="static model contract resists overlay",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("nvidia_nim",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        ),
        registry=registry,
    )
    assert decision.selected_model == "nvidia/nemotron-3-super-120b-a12b"
    assert decision.policy_metadata["provider_model_binding_source"] == "REGISTRY_STATIC"


def test_tuxevil_current_run_runtime_model_is_accepted_end_to_end(
    monkeypatch,
):
    import app.services.harness_ai_provider_service as service

    run_id = "2001"
    evidence_ref = f"github:run:{run_id}:tuxevil-live-proof"
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv(
        "BR_RUNTIME_PROVIDER_HEALTH_JSON",
        json.dumps({
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
                "evidence_refs": [evidence_ref],
            }
        }),
    )
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="semantic mission planning proposal only",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("tuxevil",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        )
    )
    assert decision.selected_provider == "tuxevil"
    assert decision.selected_model == "gemini-3-flash"
    assert decision.policy_metadata["provider_model_binding_source"] == (
        "CURRENT_RUN_RUNTIME_PROOF"
    )
    assert decision.policy_metadata["runtime_provider_binding_used"] is True
    assert evidence_ref in decision.policy_metadata["runtime_provider_evidence_refs"]

    calls = []
    class RuntimeProvider:
        pass

    monkeypatch.setattr(
        service,
        "create_ai_provider",
        lambda *, model=None: calls.append(model) or RuntimeProvider(),
    )
    provider_name, provider = service.select_harness_ai_provider(
        provider_name="tuxevil",
        authorization=auth("tuxevil"),
        routing_decision=decision,
    )
    assert provider_name == "tuxevil"
    assert isinstance(provider, RuntimeProvider)
    assert calls == ["gemini-3-flash"]


def test_provider_failure_does_not_trigger_silent_fallback(monkeypatch):
    _install_free_test_provider(
        monkeypatch,
        "nvidia_nim",
        model_id="nvidia/nemotron-3-super-120b-a12b",
    )
    from app.services.ai_provider import AIProviderError
    calls=[]
    class FailingProvider:
        def generate(self, prompt):
            calls.append(prompt)
            raise AIProviderError("primary failed")
    def selector(*, provider_name, authorization):
        calls.append(provider_name)
        return "nvidia_nim", FailingProvider()
    evidence=execute_harness_ai_generation(provider_name="nvidia",prompt="Teste",authorization=auth(),selector=selector)
    assert evidence.status == "FAILED"
    assert calls == ["nvidia", "Teste"]
    assert evidence.routing["fallback_occurred"] is False



def test_provider_constructor_integrity_error_is_captured_as_evidence(monkeypatch):
    _install_free_test_provider(
        monkeypatch,
        "opencode",
        model_id="oc/big-pickle",
    )

    def failing_selector(*, provider_name, authorization):
        assert provider_name == "opencode"
        assert authorization.authority == "deepseek_harness"
        raise PermissionError(
            "active OpenCode executor profile checksum does not match executable code"
        )

    evidence = execute_harness_ai_generation(
        provider_name="opencode",
        prompt="Teste",
        authorization=auth("opencode"),
        selector=failing_selector,
    )

    assert evidence.status == "FAILED"
    assert evidence.active is False
    assert evidence.provider == "opencode"
    assert evidence.error["code"] == "provider_profile_integrity_mismatch"
    assert evidence.error["failure_pattern"] == "opencode_profile_integrity_mismatch"
    assert evidence.error["retryable"] is False
    assert "checksum does not match executable code" in evidence.error["message"]

def _decision(provider, model, *, fallback=False):
    return HarnessRoutingDecision(
        routing_id=f"route-{provider}-{model}",
        intent="bounded semantic failover",
        authorized_action="EDITORIAL",
        candidate_capability_ids=("ai.reasoning.text",),
        selected_capability_id="ai.reasoning.text",
        selected_provider=provider,
        selected_model=model,
        selected_executor_binding=(
            "app.services.harness_ai_provider_service."
            "execute_harness_ai_generation"
        ),
        selected_provider_executor_binding=(
            "app.services.harness_ai_provider_service."
            "execute_harness_ai_generation"
            if provider == "nvidia_nim"
            else "app.services.ai_provider_factory.create_ai_provider"
            if provider == "tuxevil"
            else (
                "app.services.opencode_executor_profile_service."
                "create_opencode_provider_for_active_profile"
            )
        ),
        primary_provider="nvidia_nim",
        fallback_allowed=True,
        fallback_candidates=("tuxevil", "opencode"),
        fallback_occurred=fallback,
        evidence_expectations=("HarnessAIProviderEvidence",),
        rationale=("test fixture",),
        rejected_candidates=(),
        policy_metadata={"structured_output_required": True},
    )


def test_resilient_provider_replans_after_nvidia_timeout_to_another_nvidia_model(
    monkeypatch,
):
    import app.services.harness_ai_provider_service as service

    decisions = [
        _decision("nvidia_nim", "model-a"),
        _decision("nvidia_nim", "model-b"),
    ]
    requests = []

    def route(request):
        requests.append(request)
        return decisions[len(requests) - 1]

    class TimeoutProvider:
        def generate(self, _prompt):
            raise AIProviderError(
                "timeout",
                code="timeout",
                retryable=True,
            )

    class SuccessProvider:
        def generate(self, prompt):
            assert prompt == "Teste"
            return AIResponse(
                text='{"ok":true}',
                provider="nvidia_nim",
                model="model-b",
            )

    providers = [TimeoutProvider(), SuccessProvider()]
    monkeypatch.setattr(service, "route_harness_request", route)
    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: (
            "nvidia_nim",
            providers.pop(0),
        ),
    )
    parent = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="action:EDITORIAL",
        harness_decision_id="decision-resilient",
        execution_id="execution-resilient",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="structured editorial reasoning",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            preferred_providers=("nvidia_nim", "tuxevil", "opencode"),
            fallback_allowed=True,
            zero_cost_operation=True,
            structured_output_required=True,
            learning_required=False,
        ),
        structured_output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        },
    )
    response = provider.generate("Teste")
    assert response.model == "model-b"
    assert len(provider.last_attempts) == 2
    assert provider.last_attempts[0]["failure_code"] == "timeout"
    assert requests[1].exhausted_provider_model_pairs == (
        ("nvidia_nim", "model-a"),
    )


def test_resilient_provider_does_not_failover_on_malformed_structured_output(
    monkeypatch,
):
    import app.services.harness_ai_provider_service as service

    route_calls = []
    monkeypatch.setattr(
        service,
        "route_harness_request",
        lambda request: (
            route_calls.append(request)
            or _decision("nvidia_nim", "model-a")
        ),
    )

    class MalformedProvider:
        def generate(self, _prompt):
            raise AIProviderError(
                "malformed JSON",
                code="malformed_structured_output",
                retryable=True,
            )

    monkeypatch.setattr(
        service,
        "select_harness_ai_provider",
        lambda **_kwargs: ("nvidia_nim", MalformedProvider()),
    )
    parent = issue_harness_authorization(
        authorized_action="EDITORIAL",
        subject="action:EDITORIAL",
        harness_decision_id="decision-malformed",
        execution_id="execution-malformed",
    )
    provider = ResilientHarnessAIProvider(
        parent_authorization=parent,
        routing_request=HarnessRoutingRequest(
            intent="structured editorial reasoning",
            authorized_action="EDITORIAL",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("nvidia_nim", "tuxevil", "opencode"),
            fallback_allowed=True,
            zero_cost_operation=True,
            structured_output_required=True,
            learning_required=False,
        ),
    )
    with pytest.raises(
        AIProviderError,
        match="malformed JSON",
    ):
        provider.generate("Teste")
    assert len(route_calls) == 1
    assert provider.last_attempts[0]["recoverable"] is False

