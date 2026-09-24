from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.database.schema import initialize_schema
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_collaboration_service import CollaborationTask, build_collaboration_plan
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.hermes_multiagent.contracts import (
    HERMES_RUNTIME_CAPABILITY_ID,
    MANDATORY_FORBIDDEN_ACTIONS,
    HermesMissionExecutionSpec,
)
from app.services.hermes_multiagent.harness_tools import HermesHarnessTools
from app.services.hermes_multiagent.capability_broker import HermesHarnessCapabilityBroker
from app.services.hermes_multiagent.profile_factory import HermesProfileFactory


ROOT = Path(__file__).resolve().parents[1]


def _plan():
    return build_collaboration_plan(
        mission_id="hermes-test-mission",
        goal_id="goal-video-a",
        tasks=(
            CollaborationTask(
                task_id="verify",
                capability_id="gta6.fact-check",
                action="RESEARCH",
                objective="Verify supplied VIDEO A evidence only.",
                expected_output="verified evidence summary",
            ),
            CollaborationTask(
                task_id="critic",
                capability_id="gta6.fact-check",
                action="EDITORIAL",
                objective="Critique claims against verified evidence.",
                dependencies=("verify",),
                expected_output="editorial critique",
            ),
        ),
    )


def _auth_and_spec():
    initialize_schema()
    plan = _plan()
    decision = route_harness_request(
        HarnessRoutingRequest(
            intent="execute pinned Hermes collaboration runtime",
            authorized_action="EXECUTION",
            domain="collaboration",
            required_capability_id=HERMES_RUNTIME_CAPABILITY_ID,
            fallback_allowed=False,
            learning_required=False,
        )
    )
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject=f"capability:{HERMES_RUNTIME_CAPABILITY_ID}",
        harness_decision_id="decision-hermes-test",
        execution_id="execution-hermes-test",
        lineage={
            "routing_id": decision.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": decision.selected_executor_binding,
        },
    )
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha="a" * 40,
        expires_at="2099-01-01T00:00:00+00:00",
        profile_roles={
            "verify": "hermes-research-verifier",
            "critic": "hermes-editorial-critic",
        },
    )
    return auth, spec


def test_upstream_is_exact_sha_pinned_and_core_license_is_mit():
    lock = json.loads((ROOT / "integrations/hermes_agent/UPSTREAM.lock").read_text())
    assert lock["repository"] == "https://github.com/NousResearch/hermes-agent"
    assert lock["commit"] == "9eca7f388f71755293343dddd6ec4d9111d68fc4"
    assert lock["version"] == "0.21.3"
    assert lock["license"] == "MIT"
    assert lock["optional_skills_imported"] is False
    assert lock["optional_modules_imported"] is False
    notice = (ROOT / "integrations/hermes_agent/LICENSE").read_text()
    assert notice.startswith("MIT License")
    assert "Nous Research" in notice


def test_registry_remains_canonical_for_hermes_runtime_and_task_profiles():
    runtime = GLOBAL_CAPABILITY_REGISTRY.get(HERMES_RUNTIME_CAPABILITY_ID)
    assert runtime is not None
    assert runtime.agent_id == "hermes-runtime"
    assert runtime.allowed_actions == ("EXECUTION",)
    assert runtime.executor_binding == (
        "app.services.hermes_multiagent.runtime.execute_hermes_mission_capability"
    )

    plan = _plan()
    profiles = HermesProfileFactory().project_plan(
        plan,
        role_by_task={
            "verify": "hermes-research-verifier",
            "critic": "hermes-editorial-critic",
        },
    )
    assert [p.profile_name for p in profiles] == [
        "hermes-research-verifier",
        "hermes-editorial-critic",
    ]
    for profile, task in zip(profiles, plan.tasks):
        record = GLOBAL_CAPABILITY_REGISTRY.get(task.capability_id)
        assert record is not None
        assert profile.capability_id == record.capability_id
        assert profile.canonical_agent_id == record.agent_id
        assert profile.canonical_skill_id == record.skill_id
        assert profile.executor_binding == record.executor_binding
        assert profile.authority == "DELEGATED_ONLY"
        assert profile.memory_write == "FORBIDDEN"
        assert profile.publication_authority == "NONE"


def test_mission_lease_cannot_omit_mandatory_forbidden_actions():
    _auth, spec = _auth_and_spec()
    assert MANDATORY_FORBIDDEN_ACTIONS <= set(spec.forbidden_actions)
    with pytest.raises(PermissionError, match="mandatory forbidden"):
        replace(spec, forbidden_actions=("push",))


def test_profile_cannot_expand_task_scope_or_drift_executor():
    plan = _plan()
    bad = replace(
        plan.tasks[0],
        selected_executor_binding="attacker.direct_executor",
    )
    with pytest.raises(PermissionError, match="executor drift"):
        HermesProfileFactory().project_task(bad, runtime_role="hermes-research-verifier")


def test_harness_tools_refuse_scope_authority_and_secret_overrides():
    auth, spec = _auth_and_spec()
    bridge = HermesHarnessTools(spec=spec, parent_authorization=auth)

    status = bridge.br_harness_status(task_id="verify")
    assert status["authority"] == "DEEPSEEK_HARNESS"
    assert status["capability_id"] == "gta6.fact-check"

    with pytest.raises(PermissionError, match="outside the authorized mission scope"):
        bridge.br_harness_status(task_id="invented")

    with pytest.raises(PermissionError, match="override authority"):
        bridge.br_harness_capability_request(
            task_id="verify",
            payload={"executor_binding": "direct.shell", "claim": "x"},
        )

    with pytest.raises(PermissionError, match="secret"):
        bridge.br_harness_submit_evidence(
            task_id="verify",
            evidence={"api_key": "forbidden"},
        )


def test_harness_capability_request_is_governed_and_not_directly_executed():
    auth, spec = _auth_and_spec()
    bridge = HermesHarnessTools(spec=spec, parent_authorization=auth)
    result = bridge.br_harness_capability_request(
        task_id="verify",
        payload={"claim": "bounded evidence request"},
    )
    assert result["status"] == "AUTHORIZED"
    assert result["authority"] == "DEEPSEEK_HARNESS"
    assert result["capability_id"] == "gta6.fact-check"
    assert result["executed"] is False
    assert result["authorization_id"] != spec.authorization_id


def test_hermes_has_no_publication_or_canonical_memory_authority():
    policy = json.loads(
        (ROOT / "integrations/hermes_agent/config/runtime-policy.json").read_text()
    )
    assert policy["canonical_memory"] is False
    assert policy["canonical_scheduler"] is False
    assert policy["direct_publication_access"] is False
    assert "youtube_publish_public" in policy["forbidden_actions"]
    runtime = GLOBAL_CAPABILITY_REGISTRY.get(HERMES_RUNTIME_CAPABILITY_ID)
    assert runtime is not None
    assert "PUBLICATION" not in runtime.allowed_actions
    assert "YOUTUBE" not in runtime.allowed_actions

def test_agent_context_compression_preserves_direct_dependency_lineage():
    broker = HermesHarnessCapabilityBroker.__new__(HermesHarnessCapabilityBroker)
    direct = {
        "task_id": "knowledge-enrich",
        "functional_role": "GENERAL",
        "capability_id": "gta6.research.semantic-synthesis",
        "task_result_ref": "artifact:task-results/knowledge-enrich-1.json",
        "content_sha256": "a" * 64,
        "output_artifact_refs": ["research-semantic:mission:knowledge-enrich"],
        "evidence_refs": ["artifact:source-evidence.json"],
        "direct_dependency": True,
        "result": {"large": "x" * 200000},
    }
    transitive = {
        "task_id": "fact-verify",
        "task_result_ref": "artifact:task-results/fact-verify-1.json",
        "content_sha256": "b" * 64,
        "direct_dependency": False,
        "result": {"large": "y" * 200000},
    }
    context = {
        "mission_id": "mission-context-budget",
        "task_id": "editorial-script",
        "goal_id": "goal-context-budget",
        "task": {"objective": "produce editorial script"},
        "parent_handoffs": [direct, transitive],
        "evidence_refs": ["artifact:source-evidence.json"],
        "relevant_memory": {"blob": "m" * 200000},
        "dependency_context_sha256": "c" * 64,
    }

    compressed = broker._next_agent_context(
        base_context=context,
        tool_results=[],
        previous_output="",
        agent_turn=1,
    )

    handoffs = compressed.get("parent_handoffs") or []
    assert len(handoffs) == 1
    assert handoffs[0]["task_id"] == "knowledge-enrich"
    assert handoffs[0]["direct_dependency"] is True
    assert handoffs[0]["task_result_ref"] == (
        "artifact:task-results/knowledge-enrich-1.json"
    )
    assert handoffs[0]["content_sha256"] == "a" * 64
    assert "result" not in handoffs[0]
    assert compressed["dependency_context_sha256"] == "c" * 64
