from app.services.ai_provider import AIResponse, AIUsage
from app.services.harness_ai_provider_service import (
    HarnessAIProviderAuthorization,
    execute_harness_ai_generation,
    select_harness_ai_provider,
)


AUTH = HarnessAIProviderAuthorization(
    authority="deepseek_harness",
    authorized_action="EDITORIAL",
    harness_decision_id="decision-1",
    execution_id="execution-1",
)


class FakeProvider:
    def generate(self, prompt):
        assert prompt == "Teste"
        return AIResponse(
            text="OK",
            provider="nvidia_nim",
            model="nvidia/nemotron-3-super-120b-a12b",
            reasoning_content="reasoning",
            usage=AIUsage(
                prompt_tokens=1,
                completion_tokens=2,
                total_tokens=3,
            ),
            finish_reason="stop",
        )


def test_harness_boundary_returns_normalized_lineage_evidence():
    def selector(*, provider_name, authorization):
        assert provider_name == "nvidia"
        assert authorization.authority == "deepseek_harness"
        return "nvidia_nim", FakeProvider()

    evidence = execute_harness_ai_generation(
        provider_name="nvidia",
        prompt="Teste",
        authorization=AUTH,
        selector=selector,
    )
    assert evidence.status == "EXECUTED"
    assert evidence.provider == "nvidia_nim"
    assert evidence.authority == "deepseek_harness"
    assert evidence.result["text"] == "OK"
    assert evidence.result["reasoning_content"] == "reasoning"
    assert evidence.result["usage"]["total_tokens"] == 3


def test_non_harness_authority_is_rejected_before_provider_selection():
    bad = HarnessAIProviderAuthorization(
        authority="parallel_agent",
        authorized_action="EDITORIAL",
        harness_decision_id="d",
        execution_id="e",
    )
    try:
        select_harness_ai_provider(
            provider_name="nvidia",
            authorization=bad,
        )
    except PermissionError as exc:
        assert "sole AI provider authority" in str(exc)
    else:
        raise AssertionError("expected PermissionError")


def test_nvidia_selection_is_lazy_and_policy_owned(monkeypatch):
    import app.services.harness_ai_provider_service as service

    calls = []

    class SelectedProvider:
        pass

    monkeypatch.setattr(
        service,
        "NvidiaNIMProvider",
        lambda: calls.append("nvidia") or SelectedProvider(),
    )
    provider_name, provider = service.select_harness_ai_provider(
        provider_name="nvidia",
        authorization=AUTH,
    )
    assert provider_name == "nvidia_nim"
    assert isinstance(provider, SelectedProvider)
    assert calls == ["nvidia"]


def test_tuxevil_selection_does_not_construct_nvidia(monkeypatch):
    import app.services.harness_ai_provider_service as service

    monkeypatch.setattr(
        service,
        "NvidiaNIMProvider",
        lambda: (_ for _ in ()).throw(
            AssertionError("NVIDIA must not be touched")
        ),
    )
    expected = object()
    monkeypatch.setattr(service, "create_ai_provider", lambda: expected)
    provider_name, provider = service.select_harness_ai_provider(
        provider_name="tuxevil",
        authorization=AUTH,
    )
    assert provider_name == "tuxevil"
    assert provider is expected
