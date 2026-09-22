from __future__ import annotations

import pytest

from app.services import addy_harness_service
from app.services.addy_harness_service import (
    ADDY_EXECUTOR_BINDING,
    execute_authorized_addy_skill,
)
from app.services.global_capability_registry_base import (
    ADDY_SKILLS,
    GLOBAL_CAPABILITY_REGISTRY,
)
from app.services.harness_ai_provider_service import HarnessAIProviderEvidence
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_routing_policy_service import (
    HarnessRoutingRequest,
    route_harness_request,
)
from app.services.provider_health_service import ProviderHealth


def _install_healthy_opencode_contract_fixture(monkeypatch) -> None:
    import app.services.provider_health_service as health_service

    original = health_service.provider_health

    def provider_health(provider_id: str, **kwargs):
        if str(provider_id).strip().lower().replace("-", "_") == "opencode":
            return ProviderHealth(
                provider_id="opencode",
                state="AVAILABLE",
                reason="deterministic contract fixture",
                evidence_refs=("test:addy-24:provider-health",),
                retry_allowed=True,
                zero_cost_eligible=True,
            )
        return original(provider_id, **kwargs)

    monkeypatch.setattr(
        health_service,
        "provider_health",
        provider_health,
    )


@pytest.mark.parametrize("skill_name", ADDY_SKILLS)
def test_each_addy_skill_has_governed_harness_execution_contract(
    skill_name: str,
    monkeypatch,
):
    _install_healthy_opencode_contract_fixture(monkeypatch)
    capability_id = f"addy:{skill_name}"
    record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
    assert record is not None
    assert record.available is True
    assert record.execution_enabled is True
    assert record.agent_id == "addy-agent-skills"
    assert record.skill_id == skill_name
    assert record.executor_binding == ADDY_EXECUTOR_BINDING

    routing = route_harness_request(
        HarnessRoutingRequest(
            intent=f"execute pinned Addy skill {skill_name}",
            authorized_action="DEVELOPMENT",
            domain="development",
            task_class=f"test-addy:{skill_name}",
            goal_id=f"goal-addy-{skill_name}",
            required_capability_id=capability_id,
            fallback_allowed=False,
            provider_required=False,
            learning_required=True,
        )
    )
    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{capability_id}",
        harness_decision_id=f"addy-24-decision-{skill_name}",
        execution_id=f"addy-24-execution-{skill_name}",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": routing.selected_capability_id,
            "selected_executor_binding": routing.selected_executor_binding,
            "goal_id": f"goal-addy-{skill_name}",
        },
    )

    monkeypatch.setattr(
        addy_harness_service,
        "resolve_pinned_addy_skill",
        lambda name: (
            f"# {name}\nUse evidence-first engineering and return a bounded result.",
            "be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39",
            "0" * 64,
        ),
    )

    def fake_generate(*, prompt, authorization, routing_decision, **kwargs):
        assert f"SELECTED_SKILL={skill_name}" in prompt
        assert routing_decision.selected_provider == "opencode"
        assert routing_decision.selected_model == "oc/big-pickle"
        return HarnessAIProviderEvidence(
            provider="opencode",
            status="EXECUTED",
            active=True,
            authority="deepseek_harness",
            authorized_action="DEVELOPMENT",
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            authorization_id=authorization.authorization_id,
            result={"text": f"certified:{skill_name}", "model": "oc/big-pickle"},
            routing=routing_decision.to_dict(),
            model="oc/big-pickle",
            executor_binding=routing_decision.selected_provider_executor_binding,
            latency_seconds=0.01,
            evidence_refs=(f"provider-routing:{skill_name}",),
            provider_profile_skill_id="ai.reasoning.opencode-executor-profile",
            provider_profile_version="v2",
            provider_profile_content_ref="python:test:v2",
            provider_profile_checksum="1" * 64,
        )

    monkeypatch.setattr(addy_harness_service, "execute_harness_ai_generation", fake_generate)
    monkeypatch.setattr(
        addy_harness_service,
        "capture_canonical_execution_episode",
        lambda *args, **kwargs: {"status": "captured"},
    )

    try:
        evidence = execute_authorized_addy_skill(
            authorization=authorization,
            routing_decision=routing,
            payload={
                "mission_id": "mission-addy-24-unit",
                "task_id": skill_name,
                "goal_id": f"goal-addy-{skill_name}",
                "task": f"Certification probe for {skill_name}.",
                "evidence_refs": [f"test:{skill_name}"],
            },
        )
    finally:
        consume_harness_authorization(authorization)

    assert evidence.status == "EXECUTED"
    assert evidence.active is True
    assert evidence.authority == "deepseek_harness"
    assert evidence.result["skill"] == skill_name
    assert evidence.result["output"] == f"certified:{skill_name}"
    assert evidence.result["semantic_provider"] == "opencode"
    assert evidence.result["semantic_model"] == "oc/big-pickle"
    receipt = evidence.result["receipt"]
    assert receipt["skill_id"] == skill_name
    assert receipt["external_call_performed"] is True
    assert receipt["returned_to_harness"] is True
    assert receipt["proven_live"] is True


def test_addy_certification_inventory_is_exactly_24_unique_skills():
    assert len(ADDY_SKILLS) == 24
    assert len(set(ADDY_SKILLS)) == 24
    assert "browser-testing-with-devtools" not in ADDY_SKILLS


def test_addy_nested_semantic_provider_is_harness_selected_not_hardcoded(
    monkeypatch,
):
    skill_name = "code-review-and-quality"
    capability_id = f"addy:{skill_name}"

    import app.services.provider_health_service as health_service

    original_provider_health = health_service.provider_health

    def controlled_health(provider_id: str, **kwargs):
        normalized = str(provider_id).strip().lower().replace("-", "_")
        if normalized == "opencode":
            return ProviderHealth(
                provider_id="opencode",
                state="UPSTREAM_DENIED",
                reason="deterministic blocked fixture",
                evidence_refs=("test:opencode:blocked",),
                retry_allowed=False,
                zero_cost_eligible=True,
            )
        if normalized == "nvidia_nim":
            return ProviderHealth(
                provider_id="nvidia_nim",
                state="AVAILABLE",
                reason="deterministic healthy NVIDIA fixture",
                evidence_refs=("test:nvidia:available",),
                retry_allowed=True,
                zero_cost_eligible=True,
            )
        return ProviderHealth(
            provider_id=normalized,
            state="BLOCKED",
            reason="deterministic non-candidate fixture",
            evidence_refs=(),
            retry_allowed=False,
            zero_cost_eligible=True,
        )

    monkeypatch.setattr(
        health_service,
        "provider_health",
        controlled_health,
    )
    monkeypatch.setattr(
        addy_harness_service,
        "semantic_provider_health",
        health_service.semantic_provider_health,
    )
    monkeypatch.setattr(
        addy_harness_service,
        "resolve_pinned_addy_skill",
        lambda name: (
            f"# {name}\nReturn a bounded evidence-first review.",
            "be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39",
            "2" * 64,
        ),
    )
    monkeypatch.setattr(
        addy_harness_service,
        "capture_canonical_execution_episode",
        lambda *args, **kwargs: {"status": "captured"},
    )

    outer = route_harness_request(
        HarnessRoutingRequest(
            intent=f"execute pinned Addy skill {skill_name}",
            authorized_action="DEVELOPMENT",
            domain="development",
            task_class="test-addy-provider-pool",
            goal_id="goal-addy-provider-pool",
            required_capability_id=capability_id,
            provider_required=False,
            preferred_providers=("opencode",),
            unavailable_provider_ids=("opencode",),
            fallback_allowed=False,
            learning_required=True,
        )
    )
    assert outer.selected_provider is None
    assert outer.fallback_occurred is False

    authorization = issue_harness_authorization(
        authorized_action="DEVELOPMENT",
        subject=f"capability:{capability_id}",
        harness_decision_id="addy-provider-pool-decision",
        execution_id="addy-provider-pool-execution",
        lineage={
            "routing_id": outer.routing_id,
            "capability_id": outer.selected_capability_id,
            "selected_executor_binding": outer.selected_executor_binding,
            "goal_id": "goal-addy-provider-pool",
        },
    )

    def fake_generate(*, routing_decision, authorization, **kwargs):
        assert routing_decision.selected_provider == "nvidia_nim"
        assert routing_decision.selected_model
        assert routing_decision.fallback_occurred is False
        return HarnessAIProviderEvidence(
            provider="nvidia_nim",
            status="EXECUTED",
            active=True,
            authority="deepseek_harness",
            authorized_action="DEVELOPMENT",
            harness_decision_id=authorization.harness_decision_id,
            execution_id=authorization.execution_id,
            authorization_id=authorization.authorization_id,
            result={
                "text": "nvidia-governed-review",
                "model": routing_decision.selected_model,
            },
            routing=routing_decision.to_dict(),
            model=routing_decision.selected_model,
            executor_binding=routing_decision.selected_provider_executor_binding,
            latency_seconds=0.01,
            evidence_refs=("test:nvidia:routed",),
        )

    monkeypatch.setattr(
        addy_harness_service,
        "execute_harness_ai_generation",
        fake_generate,
    )
    try:
        evidence = execute_authorized_addy_skill(
            authorization=authorization,
            routing_decision=outer,
            payload={
                "mission_id": "mission-addy-provider-pool",
                "task_id": "review",
                "goal_id": "goal-addy-provider-pool",
                "task": "Review this bounded candidate.",
            },
        )
    finally:
        consume_harness_authorization(authorization)

    assert evidence.status == "EXECUTED"
    assert evidence.result["semantic_provider"] == "nvidia_nim"
    assert evidence.result["semantic_model"]
