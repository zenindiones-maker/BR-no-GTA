import json
from unittest.mock import patch

import pytest

from app.services.ai_provider import AIResponse
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_ai_provider_service import select_harness_ai_provider
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.local_openweight_ai_provider import (
    LOCAL_OPENWEIGHT_MODEL_DIGEST,
    LOCAL_OPENWEIGHT_MODEL_ID,
    OllamaLocalAIProvider,
)
from app.services.provider_health_service import provider_health


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _auth():
    return issue_harness_authorization(
        authorized_action="DECISION",
        subject="provider:ollama_local",
        harness_decision_id="decision-local-openweight",
        execution_id="execution-local-openweight",
    )


def test_registry_classifies_only_proven_local_runtime_as_free_no_billing():
    record = GLOBAL_CAPABILITY_REGISTRY.get("ai.provider.ollama-local-qwen3-4b")
    assert record is not None
    assert record.provider_id == "ollama_local"
    assert record.model_id == LOCAL_OPENWEIGHT_MODEL_ID
    assert record.cost_class == "FREE_NO_BILLING"
    assert record.quota_class == "PUBLIC_STANDARD_GITHUB_ACTIONS_LOCAL_RUNTIME"
    assert record.availability == "AVAILABLE"
    assert "no external provider credentials" in record.requirements
    assert record.fallback_eligibility is False


def test_local_provider_is_fail_closed_to_exact_model_and_loopback():
    with pytest.raises(PermissionError, match="model identity mismatch"):
        OllamaLocalAIProvider(model="another-model")
    with pytest.raises(PermissionError, match="loopback-only"):
        OllamaLocalAIProvider(
            model=LOCAL_OPENWEIGHT_MODEL_ID,
            base_url="https://example.com",
        )


def test_local_provider_normalizes_real_ollama_shape():
    payload = {
        "model": LOCAL_OPENWEIGHT_MODEL_ID,
        "message": {"role": "assistant", "content": "LOCAL OK"},
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 7,
        "eval_count": 3,
    }
    provider = OllamaLocalAIProvider(model=LOCAL_OPENWEIGHT_MODEL_ID)
    with patch(
        "app.services.local_openweight_ai_provider.request.urlopen",
        return_value=FakeResponse(payload),
    ):
        response = provider.generate("Teste")
    assert isinstance(response, AIResponse)
    assert response.text == "LOCAL OK"
    assert response.provider == "ollama_local"
    assert response.model == LOCAL_OPENWEIGHT_MODEL_ID
    assert response.usage.total_tokens == 10


def test_zero_cost_routing_can_select_only_registered_local_model():
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="semantic mission planning proposal only",
            authorized_action="DECISION",
            domain="ai",
            task_class="semantic-mission-planning",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("ollama_local",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=False,
        )
    )
    assert decision.selected_provider == "ollama_local"
    assert decision.selected_model == LOCAL_OPENWEIGHT_MODEL_ID
    assert decision.selected_provider_executor_binding.endswith(
        "local_openweight_ai_provider.OllamaLocalAIProvider"
    )
    assert decision.fallback_occurred is False


def test_harness_constructs_local_provider_only_after_authorized_routing():
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="semantic mission planning proposal only",
            authorized_action="DECISION",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            preferred_providers=("ollama_local",),
            fallback_allowed=False,
            zero_cost_operation=True,
        )
    )
    provider_id, provider = select_harness_ai_provider(
        authorization=_auth(),
        routing_decision=decision,
    )
    assert provider_id == "ollama_local"
    assert isinstance(provider, OllamaLocalAIProvider)
    assert provider.model == LOCAL_OPENWEIGHT_MODEL_ID


def test_local_provider_health_requires_live_runtime_enablement(monkeypatch):
    monkeypatch.delenv("BR_LOCAL_OPENWEIGHT_ENABLED", raising=False)
    health = provider_health("ollama_local")
    assert health.state == "BLOCKED"
    assert health.zero_cost_eligible is True


def test_local_provider_health_requires_exact_live_digest(monkeypatch):
    monkeypatch.setenv("BR_LOCAL_OPENWEIGHT_ENABLED", "1")
    payload = {
        "models": [
            {
                "name": LOCAL_OPENWEIGHT_MODEL_ID,
                "digest": LOCAL_OPENWEIGHT_MODEL_DIGEST,
            }
        ]
    }
    with patch(
        "app.services.provider_health_service.request.urlopen",
        return_value=FakeResponse(payload),
    ):
        health = provider_health("ollama_local")
    assert health.state == "AVAILABLE"
    assert health.zero_cost_eligible is True
    assert "github:run:35658908009" in health.evidence_refs


def test_local_provider_health_quarantines_digest_drift(monkeypatch):
    monkeypatch.setenv("BR_LOCAL_OPENWEIGHT_ENABLED", "1")
    payload = {
        "models": [
            {
                "name": LOCAL_OPENWEIGHT_MODEL_ID,
                "digest": "0" * 64,
            }
        ]
    }
    with patch(
        "app.services.provider_health_service.request.urlopen",
        return_value=FakeResponse(payload),
    ):
        health = provider_health("ollama_local")
    assert health.state == "QUARANTINED"
    assert health.zero_cost_eligible is False
    assert health.retry_allowed is False
