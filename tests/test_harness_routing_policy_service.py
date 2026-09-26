from dataclasses import replace
import json

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


@pytest.fixture(autouse=True)
def _current_run_nvidia_model_health(monkeypatch):
    run_id = "routing-policy-nvidia-live-fixture"
    models = [
        str(record.model_id)
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.provider_id == "nvidia_nim" and record.model_id
    ]
    monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture-key")
    monkeypatch.setenv(
        "BR_RUNTIME_MODEL_HEALTH_JSON",
        json.dumps({
            "nvidia_nim": {
                model_id: {
                    "availability": "AVAILABLE",
                    "latency_ms": 1000,
                    "confidence": 0.9,
                    "sample_size": 1,
                    "rate_limit_state": "CLEAR",
                    "circuit_breaker_state": "CLOSED",
                    "github_run_id": run_id,
                    "evidence_refs": [
                        f"github:run:{run_id}:nvidia-model:fixture"
                    ],
                }
                for model_id in models
            }
        }),
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
    matches = []
    for rejection in exc.evidence.get("rejected_candidates", []):
        candidate = str(rejection.get("candidate_id") or "")
        if (
            candidate == capability_id
            or (
                capability_id == "ai.provider.nvidia-nim"
                and candidate.startswith("ai.provider.nvidia-nim.")
            )
        ):
            matches.extend(rejection.get("reasons", ()))
    return tuple(matches)


def _nvidia_pool_models() -> set[str]:
    return {
        str(record.model_id)
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.provider_id == "nvidia_nim"
        and record.cost_class == "FREE_ENDPOINT"
    }


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
    assert decision.selected_model in _nvidia_pool_models()
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
    assert decision.selected_model in _nvidia_pool_models()


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


def test_provider_optional_capability_ignores_unavailable_provider_candidates(monkeypatch):
    import app.services.provider_health_service as health_service

    def forbidden_health_lookup(*args, **kwargs):
        raise AssertionError(
            "provider health must not be evaluated when provider_required=False"
        )

    monkeypatch.setattr(
        health_service,
        "provider_health",
        forbidden_health_lookup,
    )
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="execute pinned Addy skill using-agent-skills",
            authorized_action="DEVELOPMENT",
            domain="development",
            required_capability_id="addy:using-agent-skills",
            provider_required=False,
            preferred_providers=("opencode",),
            unavailable_provider_ids=("opencode",),
            fallback_allowed=False,
            learning_required=False,
        )
    )
    assert decision.selected_capability_id == "addy:using-agent-skills"
    assert decision.selected_provider is None
    assert decision.selected_model is None
    assert decision.primary_provider is None
    assert decision.fallback_candidates == ()
    assert decision.fallback_occurred is False


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
    assert decision.selected_model in _nvidia_pool_models()
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
    assert decision.selected_model in _nvidia_pool_models()
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


def test_real_nvidia_free_endpoint_profiles_are_zero_cost_but_quota_is_unproven():
    records = [
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.provider_id == "nvidia_nim"
    ]
    assert len(records) >= 5
    assert all(record.available is True for record in records)
    assert all(record.cost_class == "FREE_ENDPOINT" for record in records)
    assert all(
        "rate-limit-or-quota:POSSIBLE" in record.requirements
        for record in records
    )
    assert all(
        "unlimited:UNPROVEN" in record.requirements
        for record in records
    )
    decision = route_harness_request(_request())
    assert decision.selected_provider == "nvidia_nim"
    assert decision.selected_model in _nvidia_pool_models()


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
                allowed_providers=("nvidia_nim", "tuxevil"),
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
                allowed_providers=("nvidia_nim", "tuxevil"),
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


def test_youtube_semantic_reasoning_routes_without_publication_authority():
    records = [
        replace(
            record,
            availability=AVAILABLE,
            cost_class="FREE_NO_BILLING",
        )
        if record.provider_id == "opencode"
        else record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
    ]
    registry = GlobalCapabilityRegistry(records)
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="youtube seo semantic reasoning over verified evidence",
            authorized_action="YOUTUBE",
            domain="ai",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            preferred_providers=("opencode",),
            allowed_providers=("opencode",),
            fallback_allowed=False,
            zero_cost_operation=True,
        ),
        registry=registry,
    )
    assert decision.selected_capability_id == "ai.reasoning.text"
    assert decision.selected_provider == "opencode"
    assert decision.selected_model == "oc/big-pickle"
    assert decision.fallback_occurred is False
    capability = GLOBAL_CAPABILITY_REGISTRY.get("ai.reasoning.text")
    provider = GLOBAL_CAPABILITY_REGISTRY.get("ai.provider.opencode-free")
    assert capability is not None and "YOUTUBE" in capability.allowed_actions
    assert provider is not None and "YOUTUBE" in provider.allowed_actions
    assert "PUBLICATION" not in capability.allowed_actions
    assert "PUBLICATION" not in provider.allowed_actions
    assert capability.side_effects == ()
    assert provider.side_effects == ()



def test_exhausted_provider_model_pair_is_filtered_before_selection():
    registry = _provider_registry()
    decision = route_harness_request(
        _request(
            provider_required=True,
            allowed_providers=("nvidia_nim",),
            preferred_providers=("nvidia_nim",),
            exhausted_provider_model_pairs=(
                ("nvidia_nim", "z-ai/glm-5.3"),
            ),
        ),
        registry=registry,
    )
    assert not (
        decision.selected_provider == "nvidia_nim"
        and decision.selected_model == "z-ai/glm-5.3"
    )
    assert decision.policy_metadata[
        "EXHAUSTED_PAIR_FILTERED_PRE_SELECTION"
    ] is True
    assert any(
        rejection.stage == "provider"
        and "provider_model_pair_exhausted" in rejection.reasons
        for rejection in decision.rejected_candidates
    )


def test_empty_effective_pool_classified_before_primary_selection():
    with pytest.raises(RoutingPolicyError) as observed:
        route_harness_request(
            _request(
                preferred_providers=("nvidia_nim",),
                allowed_providers=("nvidia_nim",),
                unavailable_provider_ids=("nvidia_nim",),
                recovery_phase="INITIAL_PROVIDER_SELECTION",
                health_eligible_provider_ids=("nvidia_nim",),
            ),
            registry=_provider_registry(),
        )
    evidence = observed.value.evidence
    assert evidence["failure_class"] == "PROVIDER_POOL_EXHAUSTED"
    assert "Primary provider is unavailable" not in str(observed.value)
    assert evidence["EFFECTIVE_ROUTING_PROVIDER_COUNT"] == 0


def test_health_available_but_mission_ineligible_supported():
    with pytest.raises(RoutingPolicyError) as observed:
        route_harness_request(
            _request(
                allowed_providers=("nvidia_nim",),
                unavailable_provider_ids=("nvidia_nim",),
                recovery_phase="PROVIDER_LEVEL_REPLAN",
                provider_level_replan_authorized=True,
                from_provider="nvidia_nim",
                health_eligible_provider_ids=("nvidia_nim",),
            ),
            registry=_provider_registry(),
        )
    evidence = observed.value.evidence
    assert evidence["HEALTH_ELIGIBLE_PROVIDER_COUNT"] == 1
    assert evidence["EFFECTIVE_ROUTING_PROVIDER_COUNT"] == 0
    snapshot = evidence["provider_eligibility_snapshot"]
    assert snapshot["schema"] == "ProviderEligibilitySnapshot/v1"
    assert snapshot["pool_state"] == "PROVIDER_POOL_EXHAUSTED"


def test_same_provider_empty_model_set_is_model_set_exhausted():
    models = tuple(sorted(_nvidia_pool_models()))
    assert models
    with pytest.raises(RoutingPolicyError) as observed:
        route_harness_request(
            _request(
                preferred_providers=("nvidia_nim",),
                allowed_providers=("nvidia_nim",),
                unavailable_model_ids=models,
                recovery_phase="SAME_PROVIDER_MODEL_REPLAN",
                health_eligible_provider_ids=("nvidia_nim",),
            ),
            registry=_provider_registry(),
        )
    assert observed.value.evidence["failure_class"] == "MODEL_SET_EXHAUSTED"


def test_provider_route_unavailable_requires_nonempty_effective_pool():
    with pytest.raises(RoutingPolicyError) as observed:
        route_harness_request(
            _request(
                preferred_providers=("nvidia_nim",),
                allowed_providers=("nvidia_nim", "tuxevil"),
                unavailable_provider_ids=("nvidia_nim",),
                fallback_allowed=False,
                health_eligible_provider_ids=("nvidia_nim", "tuxevil"),
            ),
            registry=_provider_registry(fallback=True),
        )
    evidence = observed.value.evidence
    assert evidence["failure_class"] == "PROVIDER_ROUTE_UNAVAILABLE"
    assert evidence["EFFECTIVE_ROUTING_PROVIDER_COUNT"] > 0


def test_provider_level_replan_requires_harness_authorization():
    with pytest.raises(RoutingPolicyError) as observed:
        route_harness_request(
            _request(
                preferred_providers=(),
                allowed_providers=("nvidia_nim", "tuxevil"),
                unavailable_provider_ids=("nvidia_nim",),
                recovery_phase="PROVIDER_LEVEL_REPLAN",
                provider_level_replan_authorized=False,
                from_provider="nvidia_nim",
                health_eligible_provider_ids=("nvidia_nim", "tuxevil"),
            ),
            registry=_provider_registry(fallback=True),
        )
    evidence = observed.value.evidence
    assert evidence["failure_class"] == "PROVIDER_ROUTE_UNAVAILABLE"
    assert evidence["EFFECTIVE_ROUTING_PROVIDER_COUNT"] > 0


def test_provider_level_replan_excludes_old_provider_without_fallback():
    decision = route_harness_request(
        _request(
            preferred_providers=(),
            allowed_providers=("nvidia_nim", "tuxevil"),
            unavailable_provider_ids=("nvidia_nim",),
            recovery_phase="PROVIDER_LEVEL_REPLAN",
            provider_level_replan_authorized=True,
            from_provider="nvidia_nim",
            fallback_allowed=False,
            health_eligible_provider_ids=("nvidia_nim", "tuxevil"),
        ),
        registry=_provider_registry(fallback=True),
    )
    assert decision.selected_provider == "tuxevil"
    assert decision.fallback_allowed is False
    assert decision.fallback_occurred is False
    snapshot = decision.policy_metadata["provider_eligibility_snapshot"]
    assert "nvidia_nim" not in snapshot["effective_provider_ids"]
    assert snapshot["HARD_ELIGIBILITY_BEFORE_RANKING"] is True
