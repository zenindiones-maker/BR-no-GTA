import pytest

from app.services.ai_provider import AIResponse, AIUsage
from app.services.harness_ai_provider_service import execute_harness_ai_generation, select_harness_ai_provider
from app.services.harness_authorization_service import issue_harness_authorization


def auth(provider="nvidia_nim"):
    return issue_harness_authorization(authorized_action="EDITORIAL", subject=f"provider:{provider}", harness_decision_id="decision-1", execution_id="execution-1")


class FakeProvider:
    def generate(self, prompt):
        assert prompt == "Teste"
        return AIResponse(text="OK", provider="nvidia_nim", model="nvidia/nemotron-3-super-120b-a12b", reasoning_content="reasoning", usage=AIUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3), finish_reason="stop")


def test_harness_boundary_returns_normalized_lineage_evidence():
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


def test_fabricated_authorization_is_rejected_before_provider_selection():
    with pytest.raises(PermissionError, match="not found"):
        select_harness_ai_provider(provider_name="nvidia", authorization="fabricated")


def test_nvidia_selection_is_lazy_and_policy_owned(monkeypatch):
    import app.services.harness_ai_provider_service as service
    calls = []
    class SelectedProvider: pass
    monkeypatch.setattr(service, "NvidiaNIMProvider", lambda: calls.append("nvidia") or SelectedProvider())
    provider_name, provider = service.select_harness_ai_provider(provider_name="nvidia", authorization=auth())
    assert provider_name == "nvidia_nim" and isinstance(provider, SelectedProvider) and calls == ["nvidia"]


def test_tuxevil_selection_does_not_construct_nvidia(monkeypatch):
    import app.services.harness_ai_provider_service as service
    monkeypatch.setattr(service, "NvidiaNIMProvider", lambda: (_ for _ in ()).throw(AssertionError("NVIDIA must not be touched")))
    expected = object(); monkeypatch.setattr(service, "create_ai_provider", lambda: expected)
    provider_name, provider = service.select_harness_ai_provider(provider_name="tuxevil", authorization=auth("tuxevil"))
    assert provider_name == "tuxevil" and provider is expected
