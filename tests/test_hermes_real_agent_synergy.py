from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.database.schema import initialize_schema
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_collaboration_service import CollaborationTask, build_collaboration_plan
from app.services.harness_routing_policy_service import HarnessRoutingRequest, route_harness_request
from app.services.hermes_multiagent.capability_broker import HermesHarnessCapabilityBroker
from app.services.hermes_multiagent.contracts import HERMES_RUNTIME_CAPABILITY_ID, HermesMissionExecutionSpec
from app.services.hermes_multiagent.harness_tools import HermesHarnessTools
from app.services.hermes_multiagent.registry_roster import project_registry_to_hermes_roster


class _Board:
    def comment(self, *_args, **_kwargs):
        return 1


def _spec():
    initialize_schema()
    plan = build_collaboration_plan(
        mission_id="hermes-real-agent-broker-test",
        goal_id="goal-hermes-real-agent-broker-test",
        tasks=(
            CollaborationTask(
                task_id="improve",
                capability_id="system.improvement.propose",
                action="DEVELOPMENT",
                objective="propose an evidence-first improvement",
                expected_output="proposal only",
            ),
        ),
    )
    routing = route_harness_request(
        HarnessRoutingRequest(
            intent="execute Hermes real-agent broker test",
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
        harness_decision_id="decision-hermes-real-agent-broker-test",
        execution_id="execution-hermes-real-agent-broker-test",
        lineage={
            "routing_id": routing.routing_id,
            "capability_id": HERMES_RUNTIME_CAPABILITY_ID,
            "selected_executor_binding": routing.selected_executor_binding,
        },
    )
    spec = HermesMissionExecutionSpec.from_plan(
        collaboration_plan=plan,
        harness_decision_id=auth.harness_decision_id,
        authorization_id=auth.authorization_id,
        base_sha="a" * 40,
        expires_at="2099-01-01T00:00:00+00:00",
    )
    return auth, spec


def test_registry_projection_is_ephemeral_and_preserves_real_agent_ids():
    ids = {
        "gta6.brain.decide",
        "youtube.department.content-strategy",
        "youtube.department.script-review",
        "youtube.department.production-management",
        "system.improvement.propose",
        "agent-office.codex.readonly-analysis",
        "agent-office.codex.bounded-development",
    }
    roster = project_registry_to_hermes_roster(capability_ids=ids)
    by_id = {row.capability_id: row for row in roster}
    assert set(by_id) == ids
    assert by_id["gta6.brain.decide"].agent_id == "gta6-brain"
    assert by_id["youtube.department.content-strategy"].agent_id == "tubegent-content-strategy"
    assert by_id["youtube.department.script-review"].agent_id == "tubegent-script-review"
    assert by_id["youtube.department.production-management"].agent_id == "tubegent-production-management"
    assert by_id["system.improvement.propose"].agent_id == "system-improvement-agent"
    assert by_id["agent-office.codex.readonly-analysis"].agent_id == "codex-readonly"
    assert by_id["agent-office.codex.bounded-development"].agent_id == "codex-development"
    for capability_id, row in by_id.items():
        record = GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None
        assert row.executor_binding == record.executor_binding
        assert row.allowed_actions == record.allowed_actions
        assert row.security_boundary == record.security_boundary
        assert row.evidence_contract == record.evidence_contract


def test_harness_tools_no_longer_accept_arbitrary_execution_callback():
    params = inspect.signature(HermesHarnessTools).parameters
    assert "execution_callback" not in params
    assert "capability_broker" in params


def test_broker_executes_exact_registry_binding_under_fresh_child_authorization(tmp_path: Path):
    auth, spec = _spec()
    broker = HermesHarnessCapabilityBroker(
        spec=spec,
        parent_authorization=auth,
        board=_Board(),
        task_mapping={"improve": "board-improve"},
        artifact_dir=tmp_path,
    )
    result = broker.execute_delegated_capability(
        task_id="improve",
        capability_id="system.improvement.propose",
        payload={
            "mission_id": spec.mission_id,
            "task_id": "improve",
            "goal_id": spec.goal_id,
            "gaps": ["observed regression requires evidence-first focused coverage"],
        },
    )
    assert result["executed"] is True
    assert result["authority"] == "DEEPSEEK_HARNESS"
    assert result["agent_id"] == "system-improvement-agent"
    assert result["authorization_id"] != spec.authorization_id
    assert result["executor_binding"] == GLOBAL_CAPABILITY_REGISTRY.get(
        "system.improvement.propose"
    ).executor_binding
    payload = result["result"]
    assert payload["result"]["status"] == "PROPOSAL_ONLY"
    audit = broker.audit_snapshot()
    assert len(audit) == 1
    assert audit[0]["runtime"] == "hermes"
    assert audit[0]["policy_violations"] == 0
    assert Path(tmp_path / "capability-results/improve-1.json").is_file()


def test_broker_fails_closed_on_authority_or_executor_override(tmp_path: Path):
    auth, spec = _spec()
    broker = HermesHarnessCapabilityBroker(
        spec=spec,
        parent_authorization=auth,
        board=_Board(),
        task_mapping={"improve": "board-improve"},
        artifact_dir=tmp_path,
    )
    with pytest.raises(PermissionError, match="override authority or routing"):
        broker.execute_delegated_capability(
            task_id="improve",
            capability_id="system.improvement.propose",
            payload={
                "gaps": ["x"],
                "executor_binding": "attacker.shell",
            },
        )


def test_broker_rejects_capability_swap_even_if_other_registry_capability_exists(tmp_path: Path):
    auth, spec = _spec()
    broker = HermesHarnessCapabilityBroker(
        spec=spec,
        parent_authorization=auth,
        board=_Board(),
        task_mapping={"improve": "board-improve"},
        artifact_dir=tmp_path,
    )
    with pytest.raises(PermissionError, match="only its CollaborationPlan capability"):
        broker.execute_delegated_capability(
            task_id="improve",
            capability_id="gta6.brain.decide",
            payload={},
        )
