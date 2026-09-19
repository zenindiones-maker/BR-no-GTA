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


@pytest.mark.parametrize("skill_name", ADDY_SKILLS)
def test_each_addy_skill_has_governed_harness_execution_contract(
    skill_name: str,
    monkeypatch,
):
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
