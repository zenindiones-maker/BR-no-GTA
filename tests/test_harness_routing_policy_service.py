from dataclasses import replace

import pytest

from app.services.global_capability_registry import (
    GLOBAL_CAPABILITY_REGISTRY,
    GlobalCapabilityRegistry,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    RoutingPolicyError,
    route_harness_request,
)


def _request(**overrides):
    values = {
        "intent": "ai reasoning text",
        "authorized_action": "EDITORIAL",
        "required_capability_id": "ai.reasoning.text",
        "provider_required": True,
        "preferred_providers": ("nvidia_nim",),
    }
    values.update(overrides)
    return HarnessRoutingRequest(**values)


def _fallback_registry():
    records = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.provider_id in {"nvidia_nim", "tuxevil"}:
            record = replace(record, fallback_eligibility=True)
        records.append(record)
    return GlobalCapabilityRegistry(records)


def test_registry_discovery_feeds_routing():
    class SpyRegistry:
        def __init__(self):
            self.calls = []

        def all(self):
            return GLOBAL_CAPABILITY_REGISTRY.all()

        def get(self, capability_id):
            return GLOBAL_CAPABILITY_REGISTRY.get(capability_id)

        def discover(self, **kwargs):
            self.calls.append(kwargs)
            return GLOBAL_CAPABILITY_REGISTRY.discover(**kwargs)

    registry = SpyRegistry()
    decision = route_harness_request(_request(), registry=registry)
    assert registry.calls
    assert decision.selected_capability_id == "ai.reasoning.text"


def test_routing_does_not_authorize_or_execute(monkeypatch):
    import app.services.harness_routing_policy_service as service

    assert not hasattr(service, "issue_harness_authorization")
    decision = route_harness_request(_request())
    assert decision.selected_executor_binding
    assert "authorization_id" not in decision.to_dict()


def test_blocked_capability_is_never_selected():
    with pytest.raises(RoutingPolicyError, match="No executable capability"):
        route_harness_request(
            HarnessRoutingRequest(
                intent="higgsfield generation",
                authorized_action="EXECUTION",
                required_capability_id="higgsfield-generate",
            )
        )


def test_unknown_capability_is_never_auto_promoted():
    with pytest.raises(RoutingPolicyError, match="No executable capability"):
        route_harness_request(
            HarnessRoutingRequest(
                intent="gta6 fact check",
                authorized_action="EDITORIAL",
                required_capability_id="gta6.fact-check",
            )
        )


def test_authorized_action_filters_candidates():
    with pytest.raises(RoutingPolicyError):
        route_harness_request(
            HarnessRoutingRequest(
                intent="editorial queue",
                authorized_action="EXECUTION",
                required_capability_id="editorial.process",
                domain="editorial",
            )
        )


def test_security_boundary_filters_candidates():
    with pytest.raises(RoutingPolicyError):
        route_harness_request(
            _request(required_security_terms=("nonexistent-security-boundary",))
        )


def test_provider_model_and_capability_are_separate():
    decision = route_harness_request(_request())
    assert decision.selected_capability_id == "ai.reasoning.text"
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_model == "nvidia/nemotron-3-super-120b-a12b"
    assert decision.selected_capability_id != decision.selected_provider
    assert decision.selected_provider != decision.selected_model


def test_routing_is_deterministic_for_identical_inputs():
    request = _request()
    first = route_harness_request(request)
    second = route_harness_request(request)
    assert first.to_dict() == second.to_dict()


def test_explicit_primary_provider_is_preserved():
    decision = route_harness_request(
        _request(preferred_providers=("tuxevil",))
    )
    assert decision.primary_provider == "tuxevil"
    assert decision.selected_provider == "tuxevil"
    assert decision.fallback_occurred is False


def test_fallback_is_absent_when_policy_disallows_it():
    decision = route_harness_request(
        _request(
            preferred_providers=("nvidia_nim", "tuxevil"),
            fallback_allowed=False,
        ),
        registry=_fallback_registry(),
    )
    assert decision.fallback_candidates == ()
    assert decision.fallback_occurred is False


def test_unavailable_primary_without_fallback_fails_closed():
    with pytest.raises(RoutingPolicyError, match="fallback is not permitted"):
        route_harness_request(
            _request(
                preferred_providers=("nvidia_nim", "tuxevil"),
                unavailable_provider_ids=("nvidia_nim",),
                fallback_allowed=False,
            ),
            registry=_fallback_registry(),
        )


def test_explicit_fallback_records_evidence_and_uses_only_eligible_candidate():
    decision = route_harness_request(
        _request(
            preferred_providers=("nvidia_nim", "tuxevil"),
            unavailable_provider_ids=("nvidia_nim",),
            fallback_allowed=True,
        ),
        registry=_fallback_registry(),
    )
    assert decision.primary_provider == "nvidia_nim"
    assert decision.selected_provider == "tuxevil"
    assert decision.fallback_occurred is True
    assert any("explicit fallback" in item for item in decision.rationale)


def test_nvidia_nemotron_is_selectable_when_available():
    decision = route_harness_request(_request(preferred_providers=("nvidia",)))
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_model == "nvidia/nemotron-3-super-120b-a12b"


def test_tuxevil_is_selected_only_through_harness_policy():
    decision = route_harness_request(
        _request(preferred_providers=("tuxevil",))
    )
    assert decision.selected_provider == "tuxevil"
    assert decision.selected_provider_executor_binding.endswith(
        "ai_provider_factory.create_ai_provider"
    )


def test_gemini_unknown_is_not_selected_automatically():
    decision = route_harness_request(
        _request(preferred_providers=())
    )
    assert decision.selected_provider != "gemini"
    assert all(
        rejection.candidate_id != "ai.provider.gemini"
        or any("availability=" in reason for reason in rejection.reasons)
        for rejection in decision.rejected_candidates
    )


def test_higgsfield_blocked_is_not_selected_as_ai_provider():
    decision = route_harness_request(_request(preferred_providers=()))
    assert decision.selected_provider != "higgsfield"


def test_addy_codex_remains_bounded_to_selected_skill_executor():
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="code review quality",
            authorized_action="DEVELOPMENT",
            required_capability_id="addy:code-review-and-quality",
            domain="development",
        )
    )
    assert decision.selected_capability_id == "addy:code-review-and-quality"
    assert "codex_addy_capability_executor" in decision.selected_executor_binding
    assert decision.selected_provider is None


def test_master_agent_cannot_choose_provider_sovereignly():
    from app.services.gta6_master_agent import GTA6MasterAgent

    with pytest.raises(PermissionError, match="Harness-routed AI provider"):
        GTA6MasterAgent()
