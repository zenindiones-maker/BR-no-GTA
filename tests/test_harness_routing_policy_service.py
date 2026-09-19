from dataclasses import replace

import pytest

from app.services.global_capability_registry import (
    AVAILABLE,
    GLOBAL_CAPABILITY_REGISTRY,
    GlobalCapabilityRegistry,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    RoutingPolicyError,
    route_harness_request,
)
from app.services.zero_cost_policy_service import ZERO_COST_OPERATION


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


def _provider_registry(
    *,
    nvidia_cost="FREE_NO_BILLING",
    tuxevil_cost="FREE_NO_BILLING",
    fallback=False,
):
    records = []
    for record in GLOBAL_CAPABILITY_REGISTRY.all():
        if record.provider_id == "nvidia_nim":
            record = replace(
                record,
                availability=AVAILABLE,
                cost_class=nvidia_cost,
                fallback_eligibility=fallback,
            )
        elif record.provider_id == "tuxevil":
            record = replace(
                record,
                availability=AVAILABLE,
                cost_class=tuxevil_cost,
                fallback_eligibility=fallback,
            )
        records.append(record)
    return GlobalCapabilityRegistry(records)


def _rejection_reasons(exc: RoutingPolicyError, capability_id: str) -> tuple[str, ...]:
    for rejection in exc.evidence.get("rejected_candidates", []):
        if rejection.get("candidate_id") == capability_id:
            return tuple(rejection.get("reasons", ()))
    return ()


def test_registry_discovery_feeds_routing():
    class SpyRegistry:
        def __init__(self, delegate):
            self.delegate = delegate
            self.calls = []

        def all(self):
            return self.delegate.all()

        def get(self, capability_id):
            return self.delegate.get(capability_id)

        def discover(self, **kwargs):
            self.calls.append(kwargs)
            return self.delegate.discover(**kwargs)

    registry = SpyRegistry(_provider_registry())
    decision = route_harness_request(_request(), registry=registry)
    assert registry.calls
    assert decision.selected_capability_id == "ai.reasoning.text"


def test_routing_does_not_authorize_or_execute():
    import app.services.harness_routing_policy_service as service

    assert not hasattr(service, "issue_harness_authorization")
    decision = route_harness_request(_request(), registry=_provider_registry())
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
                intent="unregistered capability",
                authorized_action="EDITORIAL",
                required_capability_id="unknown.unregistered-capability",
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
            _request(required_security_terms=("nonexistent-security-boundary",)),
            registry=_provider_registry(),
        )


def test_provider_model_and_capability_are_separate():
    decision = route_harness_request(_request(), registry=_provider_registry())
    assert decision.selected_capability_id == "ai.reasoning.text"
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_model == "nvidia/nemotron-3-super-120b-a12b"
    assert decision.selected_capability_id != decision.selected_provider
    assert decision.selected_provider != decision.selected_model


def test_routing_is_deterministic_for_identical_inputs():
    request = _request()
    registry = _provider_registry()
    first = route_harness_request(request, registry=registry)
    second = route_harness_request(request, registry=registry)
    assert first.to_dict() == second.to_dict()


def test_explicit_primary_provider_is_preserved():
    decision = route_harness_request(
        _request(preferred_providers=("tuxevil",)),
        registry=_provider_registry(),
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
        registry=_provider_registry(fallback=True),
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
            registry=_provider_registry(fallback=True),
        )


def test_explicit_fallback_records_evidence_and_uses_only_eligible_candidate():
    decision = route_harness_request(
        _request(
            preferred_providers=("nvidia_nim", "tuxevil"),
            unavailable_provider_ids=("nvidia_nim",),
            fallback_allowed=True,
        ),
        registry=_provider_registry(fallback=True),
    )
    assert decision.primary_provider == "nvidia_nim"
    assert decision.selected_provider == "tuxevil"
    assert decision.fallback_occurred is True
    assert any("explicit fallback" in item for item in decision.rationale)


def test_nvidia_nemotron_is_selectable_when_zero_cost_is_proven():
    decision = route_harness_request(
        _request(preferred_providers=("nvidia",)),
        registry=_provider_registry(nvidia_cost="FREE_NO_BILLING"),
    )
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_model == "nvidia/nemotron-3-super-120b-a12b"


def test_tuxevil_is_selected_only_through_harness_policy_when_zero_cost_is_proven():
    decision = route_harness_request(
        _request(preferred_providers=("tuxevil",)),
        registry=_provider_registry(tuxevil_cost="FREE_NO_BILLING"),
    )
    assert decision.selected_provider == "tuxevil"
    assert decision.selected_provider_executor_binding.endswith(
        "ai_provider_factory.create_ai_provider"
    )


def test_gemini_unknown_is_not_selected_automatically():
    decision = route_harness_request(
        _request(preferred_providers=()),
        registry=_provider_registry(),
    )
    assert decision.selected_provider != "gemini"
    assert all(
        rejection.candidate_id != "ai.provider.gemini"
        or any("availability=" in reason for reason in rejection.reasons)
        for rejection in decision.rejected_candidates
    )


def test_higgsfield_blocked_is_not_selected_as_ai_provider():
    decision = route_harness_request(
        _request(preferred_providers=()),
        registry=_provider_registry(),
    )
    assert decision.selected_provider != "higgsfield"


def test_addy_remains_bounded_to_selected_harness_semantic_executor():
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="code review quality",
            authorized_action="DEVELOPMENT",
            required_capability_id="addy:code-review-and-quality",
            domain="development",
        )
    )
    assert decision.selected_capability_id == "addy:code-review-and-quality"
    assert (
        decision.selected_executor_binding
        == "app.services.addy_harness_service.execute_authorized_addy_skill"
    )
    assert decision.selected_provider is None


def test_master_agent_cannot_choose_provider_sovereignly():
    from app.services.gta6_master_agent import GTA6MasterAgent

    with pytest.raises(PermissionError, match="Harness-routed AI provider"):
        GTA6MasterAgent()


def test_runtime_unavailable_tuxevil_is_excluded_while_nvidia_remains_eligible():
    decision = route_harness_request(
        _request(
            preferred_providers=("nvidia_nim", "tuxevil"),
            unavailable_provider_ids=("tuxevil",),
            fallback_allowed=False,
        ),
        registry=_provider_registry(fallback=True),
    )
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_model == "nvidia/nemotron-3-super-120b-a12b"
    assert decision.fallback_occurred is False
    assert any(
        rejection.candidate_id == "ai.provider.tuxevil"
        and "provider_runtime_unavailable" in rejection.reasons
        for rejection in decision.rejected_candidates
    )


def test_runtime_unavailable_tuxevil_without_fallback_fails_closed():
    with pytest.raises(
        RoutingPolicyError,
        match="fallback is not permitted",
    ):
        route_harness_request(
            _request(
                preferred_providers=("tuxevil", "nvidia_nim"),
                unavailable_provider_ids=("tuxevil",),
                fallback_allowed=False,
            ),
            registry=_provider_registry(fallback=True),
        )


def test_runtime_unavailable_tuxevil_can_fallback_only_when_policy_explicitly_allows():
    decision = route_harness_request(
        _request(
            preferred_providers=("tuxevil", "nvidia_nim"),
            unavailable_provider_ids=("tuxevil",),
            fallback_allowed=True,
        ),
        registry=_provider_registry(fallback=True),
    )
    assert decision.primary_provider == "tuxevil"
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_model == "nvidia/nemotron-3-super-120b-a12b"
    assert decision.fallback_allowed is True
    assert decision.fallback_occurred is True
    assert any("explicit fallback" in item for item in decision.rationale)


def test_zero_cost_global_policy_is_propagated_even_when_request_disables_it():
    assert ZERO_COST_OPERATION is True
    decision = route_harness_request(
        _request(zero_cost_operation=False),
        registry=_provider_registry(),
    )
    assert decision.policy_metadata["global_zero_cost_operation"] is True
    assert decision.policy_metadata["zero_cost_operation"] is True
    assert "global ZERO_COST_OPERATION policy enforced" in decision.rationale


def test_paid_route_is_blocked_by_zero_cost_policy():
    with pytest.raises(RoutingPolicyError) as exc_info:
        route_harness_request(
            _request(),
            registry=_provider_registry(nvidia_cost="PAID"),
        )
    assert "PAID_PROVIDER_FORBIDDEN" in _rejection_reasons(
        exc_info.value,
        "ai.provider.nvidia-nim",
    )


def test_unknown_cost_route_is_blocked_by_zero_cost_policy():
    with pytest.raises(RoutingPolicyError) as exc_info:
        route_harness_request(
            _request(),
            registry=_provider_registry(nvidia_cost="EXTERNAL_MODEL"),
        )
    assert "UNKNOWN_COST_PROVIDER_FORBIDDEN" in _rejection_reasons(
        exc_info.value,
        "ai.provider.nvidia-nim",
    )


def test_real_nvidia_runtime_status_does_not_imply_zero_cost_status():
    record = GLOBAL_CAPABILITY_REGISTRY.get("ai.provider.nvidia-nim")
    assert record is not None
    assert record.status == "PROVEN"
    assert record.available is True
    assert record.cost_class == "EXTERNAL_MODEL"
    with pytest.raises(RoutingPolicyError) as exc_info:
        route_harness_request(_request())
    assert "UNKNOWN_COST_PROVIDER_FORBIDDEN" in _rejection_reasons(
        exc_info.value,
        "ai.provider.nvidia-nim",
    )


def test_free_quota_exhaustion_fails_closed_without_paid_fallback():
    with pytest.raises(RoutingPolicyError) as exc_info:
        route_harness_request(
            _request(
                exhausted_free_quota_provider_ids=("nvidia_nim",),
                fallback_allowed=False,
            ),
            registry=_provider_registry(nvidia_cost="FREE_QUOTA_LIMITED"),
        )
    assert "FREE_QUOTA_EXHAUSTED" in _rejection_reasons(
        exc_info.value,
        "ai.provider.nvidia-nim",
    )


def test_paid_fallback_is_forbidden_even_when_fallback_is_allowed():
    with pytest.raises(RoutingPolicyError, match="No eligible policy-governed fallback") as exc_info:
        route_harness_request(
            _request(
                preferred_providers=("nvidia_nim", "tuxevil"),
                unavailable_provider_ids=("nvidia_nim",),
                fallback_allowed=True,
            ),
            registry=_provider_registry(
                nvidia_cost="FREE_NO_BILLING",
                tuxevil_cost="PAID",
                fallback=True,
            ),
        )
    assert "PAID_PROVIDER_FORBIDDEN" in _rejection_reasons(
        exc_info.value,
        "ai.provider.tuxevil",
    )


def test_unknown_cost_fallback_is_forbidden_even_when_fallback_is_allowed():
    with pytest.raises(RoutingPolicyError, match="No eligible policy-governed fallback") as exc_info:
        route_harness_request(
            _request(
                preferred_providers=("nvidia_nim", "tuxevil"),
                unavailable_provider_ids=("nvidia_nim",),
                fallback_allowed=True,
            ),
            registry=_provider_registry(
                nvidia_cost="FREE_NO_BILLING",
                tuxevil_cost="EXTERNAL_MODEL",
                fallback=True,
            ),
        )
    assert "UNKNOWN_COST_PROVIDER_FORBIDDEN" in _rejection_reasons(
        exc_info.value,
        "ai.provider.tuxevil",
    )
