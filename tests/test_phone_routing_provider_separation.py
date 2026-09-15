from dataclasses import replace

import pytest

from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest, RoutingPolicyError, route_harness_request,
)


def _phone_request(**changes):
    request = HarnessRoutingRequest(
        intent="control local Android phone",
        authorized_action="EXECUTION",
        domain="device/mobile-control",
        required_capability_id="phone.control",
        provider_required=True,
        preferred_providers=("mobilerun-local",),
        fallback_allowed=False,
    )
    return replace(request, **changes)


def test_phone_registry_executor_does_not_require_ai_provider():
    decision = route_harness_request(_phone_request())
    record = GLOBAL_CAPABILITY_REGISTRY.get("phone.control")
    assert record is not None
    assert decision.selected_capability_id == "phone.control"
    assert decision.selected_provider is None
    assert decision.selected_model is None
    assert decision.primary_provider is None
    assert decision.selected_provider_executor_binding is None
    assert decision.selected_executor_binding == record.executor_binding
    assert decision.policy_metadata["domain"] == "device/mobile-control"
    assert decision.policy_metadata["capability_provider_id"] == "mobilerun-local"
    assert decision.policy_metadata["implementation_provider_satisfies_request"] is True
    assert record.cost_class == "FREE_NO_BILLING"
    rendered = repr(decision.to_dict()).lower()
    for forbidden in ("nvidia-nim", "nvidia_nim", "tuxevil", "gemini"):
        assert forbidden not in rendered


def test_ai_provider_requirement_still_uses_provider_policy(monkeypatch):
    import app.services.harness_routing_policy_service as policy
    called = {"value": False}
    original = policy._select_provider
    def tracked(request, registry):
        called["value"] = True
        return original(request, registry)
    monkeypatch.setattr(policy, "_select_provider", tracked)
    request = HarnessRoutingRequest(
        intent="AI reasoning", authorized_action="DECISION",
        required_capability_id="ai.reasoning.text", provider_required=True,
        provider_domain="ai", fallback_allowed=False,
    )
    try:
        route_harness_request(request)
    except RoutingPolicyError:
        pass
    assert called["value"] is True


def test_phone_provider_mismatch_remains_fail_closed():
    with pytest.raises(RoutingPolicyError):
        route_harness_request(_phone_request(preferred_providers=("gemini",)))


def test_phone_capability_does_not_self_authorize():
    decision = route_harness_request(_phone_request())
    assert not hasattr(decision, "authorization_id")
    assert decision.authorized_action == "EXECUTION"
