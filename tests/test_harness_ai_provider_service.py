import pytest
from dataclasses import replace

from app.services.ai_provider import AIResponse, AIUsage
from app.services.global_capability_registry import (
    AVAILABLE,
    FUNCTIONAL,
    GLOBAL_CAPABILITY_REGISTRY,
    GlobalCapabilityRegistry,
)
from app.services.harness_ai_provider_service import execute_harness_ai_generation, select_harness_ai_provider
from app.services.harness_routing_policy_service import HarnessRoutingDecision
from app.services.harness_authorization_service import issue_harness_authorization


def auth(provider="nvidia_nim"):
    return issue_harness_authorization(authorized_action="EDITORIAL", subject=f"provider:{provider}", harness_decision_id="decision-1", execution_id="execution-1")


def _install_free_test_provider(monkeypatch, provider_id, *, model_id=None):
    import app.services.harness_ai_provider_service as ai_service
    import app.services.harness_routing_policy_service as routing_service

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
