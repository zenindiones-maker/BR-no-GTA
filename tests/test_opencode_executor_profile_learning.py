from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.ai_provider import AIResponse
from app.services.harness_ai_provider_service import (
    execute_harness_ai_generation,
    select_harness_ai_provider,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_learning_service import (
    create_learning_candidate,
    evaluate_candidate_from_observed_results,
    register_skill_version,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.provider_health_service import ProviderHealth
from app.services.opencode_executor_profile_service import (
    BASELINE_OPENCODE_EXECUTOR_VERSION,
    CANDIDATE_OPENCODE_EXECUTOR_VERSION,
    OPENCODE_EXECUTOR_SKILL_ID,
    SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
    OpenCodeBlockedBaselineError,
    create_opencode_provider_for_active_profile,
    executable_opencode_executor_profile,
    resolve_active_opencode_executor_profile,
)


def _install_opencode_specific_route_health(monkeypatch) -> None:
    import app.services.provider_health_service as health_service

    def deterministic_provider_health(provider_id: str, **kwargs):
        normalized = str(provider_id).strip().lower().replace("-", "_")
        if normalized == "opencode":
            return ProviderHealth(
                provider_id="opencode",
                state="AVAILABLE",
                reason="deterministic OpenCode profile contract fixture",
                evidence_refs=("test:opencode-profile:available",),
                retry_allowed=True,
                zero_cost_eligible=True,
            )
        return ProviderHealth(
            provider_id=normalized,
            state="BLOCKED",
            reason="non-OpenCode provider excluded by profile-specific fixture",
            evidence_refs=(),
            retry_allowed=False,
            zero_cost_eligible=True,
        )

    monkeypatch.setattr(
        health_service,
        "provider_health",
        deterministic_provider_health,
    )


def _route(monkeypatch):
    _install_opencode_specific_route_health(monkeypatch)
    return route_harness_request(
        HarnessRoutingRequest(
            intent="validate the governed OpenCode executor profile",
            authorized_action="DECISION",
            domain="ai",
            task_class="telegram-reasoning",
            required_capability_id="ai.reasoning.text",
            provider_required=True,
            provider_domain="ai",
            preferred_providers=("opencode",),
            allowed_providers=("opencode",),
            preferred_models=("oc/big-pickle",),
            fallback_allowed=False,
            zero_cost_operation=True,
            learning_required=True,
        )
    )


def _auth(route):
    return issue_harness_authorization(
        authorized_action="DECISION",
        subject="provider:opencode",
        harness_decision_id="decision-opencode-profile",
        execution_id="execution-opencode-profile",
        lineage={
            "routing_id": route.routing_id,
            "capability_id": route.selected_capability_id,
            "selected_provider": route.selected_provider,
            "selected_model": route.selected_model,
            "selected_executor_binding": route.selected_provider_executor_binding,
            "ingress": "telegram",
        },
    )


def test_default_opencode_profile_is_observed_blocked_v1_and_fails_closed(monkeypatch):
    route = _route(monkeypatch)
    assert route.selected_provider == "opencode"
    assert route.selected_model == "oc/big-pickle"
    assert route.fallback_allowed is False
    assert route.fallback_occurred is False
    assert "opencode_executor_profile_service" in (
        route.selected_provider_executor_binding or ""
    )

    provider_name, provider = select_harness_ai_provider(
        authorization=_auth(route),
        routing_decision=route,
    )
    assert provider_name == "opencode"
    assert provider.profile_version == BASELINE_OPENCODE_EXECUTOR_VERSION

    with pytest.raises(OpenCodeBlockedBaselineError) as exc_info:
        provider.generate("hello")
    error = exc_info.value.to_dict()
    assert error["status_code"] == 403
    assert error["observed_failure_run_id"] == 35340487375
    assert error["profile_version"] == "v1"


def test_active_v3_profile_resolves_real_native_executor(monkeypatch):
    profile = executable_opencode_executor_profile(
        SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION
    )
    register_skill_version(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        version=SEMANTIC_TEXT_OPENCODE_EXECUTOR_VERSION,
        parent_version=CANDIDATE_OPENCODE_EXECUTOR_VERSION,
        content_ref=profile["content_ref"],
        checksum=profile["checksum"],
        status="ACTIVE",
        evidence_refs=("github:run:35343942135",),
    )
    assert resolve_active_opencode_executor_profile()["version"] == "v3"

    captured = {}

    class FakeNative:
        def __init__(self, *, routing_decision, authorization, profile, **kwargs):
            captured["route"] = routing_decision
            captured["auth"] = authorization
            captured["profile"] = profile
            self.executor_binding = (
                "app.services.opencode_native_ai_provider.OpenCodeNativeAIProvider"
            )
            self.profile_version = profile["version"]
            self.profile_content_ref = profile["content_ref"]
            self.profile_checksum = profile["checksum"]

    monkeypatch.setattr(
        "app.services.opencode_native_ai_provider.OpenCodeNativeAIProvider",
        FakeNative,
    )
    route = _route(monkeypatch)
    auth = _auth(route)
    provider = create_opencode_provider_for_active_profile(
        routing_decision=route,
        authorization=auth,
    )
    assert provider.profile_version == "v3"
    assert captured["profile"]["options"]["executor_model"] == "opencode/big-pickle"
    assert captured["profile"]["options"]["semantic_contract"] == "SEMANTIC_TEXT_ONLY"


def test_harness_evidence_reports_concrete_promoted_executor(monkeypatch):
    profile = executable_opencode_executor_profile("v2")
    register_skill_version(
        skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        version="v2",
        parent_version="v1",
        content_ref=profile["content_ref"],
        checksum=profile["checksum"],
        status="ACTIVE",
        evidence_refs=("github:run:35343942135",),
    )

    @dataclass
    class FakeProvider:
        profile: dict
        executor_binding: str = (
            "app.services.opencode_native_ai_provider.OpenCodeNativeAIProvider"
        )

        @property
        def profile_version(self):
            return self.profile["version"]

        @property
        def profile_content_ref(self):
            return self.profile["content_ref"]

        @property
        def profile_checksum(self):
            return self.profile["checksum"]

        def generate(self, prompt: str):
            return AIResponse(
                text="ok",
                provider="opencode",
                model="oc/big-pickle",
                finish_reason="stop",
            )

    monkeypatch.setattr(
        "app.services.harness_ai_provider_service.create_opencode_provider_for_active_profile",
        lambda **kwargs: FakeProvider(profile),
    )
    route = _route(monkeypatch)
    auth = _auth(route)
    evidence = execute_harness_ai_generation(
        prompt="same prompt",
        authorization=auth,
        routing_decision=route,
    )
    assert evidence.status == "EXECUTED"
    assert evidence.executor_binding.endswith("OpenCodeNativeAIProvider")
    assert evidence.provider_profile_skill_id == OPENCODE_EXECUTOR_SKILL_ID
    assert evidence.provider_profile_version == "v2"
    assert evidence.provider_profile_content_ref == profile["content_ref"]
    assert evidence.provider_profile_checksum == profile["checksum"]


def _metrics(*, success: float, quality: float, latency: float):
    return {
        "task_success_rate": success,
        "quality": quality,
        "human_correction_rate": 0.0,
        "retry_rate": 0.0,
        "failure_recurrence": 1.0 - success,
        "latency_seconds": latency,
        "cost": 0.0,
        "policy_violations": 0.0,
    }


def test_observed_evaluator_can_require_task_success_improvement_not_latency():
    candidate = create_learning_candidate(
        candidate_type="SKILL_UPDATE",
        hypothesis="Use the observed working official OpenCode CLI executor.",
        domain="ai",
        task_class="telegram-reasoning",
        source_episode_ids=("episode-real-telegram-403",),
        evidence_refs=(
            "github:run:35340487375",
            "github:run:35343942135",
        ),
        target_agent_id="provider:opencode",
        target_capability_id="ai.reasoning.text",
        target_skill_id=OPENCODE_EXECUTOR_SKILL_ID,
        baseline_version="v1",
        candidate_version="v2",
        implementation_ref=executable_opencode_executor_profile("v2")["content_ref"],
        acceptance_criteria={
            "min_task_success_rate_increase": 1.0,
            "max_policy_violations": 0,
        },
    )
    fingerprint = "same-workload"
    evaluation = evaluate_candidate_from_observed_results(
        candidate_id=candidate["candidate_id"],
        baseline_observation={
            "observed": True,
            "workload_fingerprint": fingerprint,
            "metrics": _metrics(success=0.0, quality=0.0, latency=5.0),
            "evidence_refs": ("github:run:baseline",),
        },
        candidate_observation={
            "observed": True,
            "workload_fingerprint": fingerprint,
            "metrics": _metrics(success=1.0, quality=1.0, latency=8.0),
            "evidence_refs": ("github:run:candidate",),
        },
        regression_observation={
            "observed": True,
            "status": "PASS",
            "critical_failures": (),
            "evidence_refs": ("github:run:regression",),
        },
        adversarial_observation={
            "observed": True,
            "status": "PASS",
            "critical_failures": (),
            "evidence_refs": ("github:run:adversarial",),
        },
    )
    assert evaluation["evaluation_mode"] == "OBSERVED"
    assert evaluation["decision"] == "PROMOTE"
    observed = evaluation["observed_evidence"]
    assert observed["task_success_rate_increase"] == 1.0
    assert observed["measurable_improvement"] is True
