from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.services.agent_office.delegation import (
    DelegatedTaskLease,
    MANDATORY_FORBIDDEN_ACTIONS,
)
from app.services.harness_authorization_service import issue_harness_authorization
from app.services.harness_collaboration_service import TaskEnvelope
from app.services.persistent_intelligence_contracts import (
    AgentCustomRule,
    PersistentResponsibility,
    PersistentWorkTimeBudget,
    ProactiveResearchPolicy,
)
from app.services.task_result_envelope_service import build_task_result_envelope
from app.services.harness_improvement_coalition_service import TaskTopologyAssessment
from app.services.openai_agents_contracts import (
    AgentEnvironmentLease,
    OpenAIAgentSessionReceipt,
    OpenAIModelCapability,
    SelectedSkillSpec,
)
from app.services.openai_agents_runtime_service import (
    MAX_CONCURRENT_OPENAI_SUBAGENTS,
    OpenAIAgentsAPIError,
    OpenAIAgentsRuntime,
    build_openai_agent_configuration,
    build_openai_subagent_plan,
    build_tool_search_configuration,
    classify_model_eligibility,
    classify_openai_session_state,
    gpt_6_1_sol_profile,
    authorize_openai_execution_scope,
    require_bounded_computer_use,
    require_registered_openai_model,
    verify_openai_task_completion,
)


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("BR_TEST_DATABASE", str(tmp_path / "openai-agents-dd2.db"))
    from app.database.schema import initialize_schema
    initialize_schema()


def _topology(name: str, branches: int = 1) -> TaskTopologyAssessment:
    return TaskTopologyAssessment(
        topology=name,
        reasons=("TEST",),
        evidence={
            "parallelizable_branch_count": branches,
            "shared_mutable_state": False,
            "write_set_overlap": False,
        },
    )


def _auth(execution_id: str) -> str:
    auth = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:openai.agents.session",
        execution_id=execution_id,
        lineage={
            "source": "dd2-runtime-test",
            "capability_id": "openai.agents.session",
        },
    )
    return auth.authorization_id


def _task_lease(task_id: str = "task-openai-1") -> DelegatedTaskLease:
    return DelegatedTaskLease.from_mapping({
        "mission_id": "mission-openai-1",
        "task_id": task_id,
        "goal_id": "goal-openai-1",
        "harness_decision_id": "decision-openai-1",
        "authorization_id": "auth-openai-lease",
        "delegation_id": "delegation-openai-1",
        "agent_id": "openai-root-agent",
        "capability_ids": ["openai.agents.session", "openai.computer-use"],
        "base_sha": "a" * 40,
        "allowed_paths": [],
        "allowed_tools": ["openai.agents.session", "openai.computer-use"],
        "allowed_actions": ["EXECUTION"],
        "forbidden_actions": sorted(MANDATORY_FORBIDDEN_ACTIONS),
        "input_artifact_refs": [],
        "expected_outputs": ["OpenAIAgentSessionReceipt/v1"],
        "acceptance_criteria": ["Harness verifies output"],
        "evidence_requirements": ["session receipt", "trace ref"],
        "time_budget_seconds": 600,
        "cost_budget": 5.0,
        "tool_call_budget": 20,
        "retry_budget": 2,
        "max_parallelism": 3,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "escalation_conditions": ["budget exhausted", "approval required"],
        "owned_task_class": "AGENTIC_EXECUTION",
        "role": "openai-root-agent",
        "read_set": [],
        "write_set": [],
    })


def _environment_lease(task_id: str = "task-openai-1") -> AgentEnvironmentLease:
    return AgentEnvironmentLease.from_mapping({
        "lease_id": "env-lease-1",
        "environment_type": "OPENAI_HOSTED",
        "environment_id": "env_1",
        "approved_domains": ["developers.openai.com", "github.com"],
        "approved_apps": ["browser"],
        "allowed_capabilities": ["COMPUTER_USE", "SANDBOX"],
        "time_budget_seconds": 300,
        "external_tool_time_budget_seconds": 180,
        "max_artifact_bytes": 10_000_000,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        "task_lease_ref": f"delegated-task:{task_id}",
        "status": "ACTIVE",
    })


class _FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, *, method, path, body=None, idempotency_key=None):
        self.calls.append({
            "method": method,
            "path": path,
            "body": body,
            "idempotency_key": idempotency_key,
        })
        if not self.responses:
            raise AssertionError("unexpected transport call")
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def test_session_receipt_keeps_turn_completed_separate_from_br_task_success():
    receipt = OpenAIAgentSessionReceipt.from_api(
        {"id": "sess_123", "status": "idle", "environment": {"id": "env_123"}},
        turn={"id": "turn_123", "status": "completed"},
        agent_model="gpt-6.1-sol",
        reasoning_effort="high",
        multi_agent_enabled=False,
        subagent_count=0,
        tool_calls=(),
        artifacts=(),
        trace_refs=("trace:1",),
    )
    assert receipt.state == "TURN_COMPLETED"
    assert receipt.br_task_state == "VERIFICATION_PENDING"
    assert receipt.br_task_success is False


def test_classify_session_state_preserves_requires_action_and_completed_turn():
    assert classify_openai_session_state(
        session_status="in_progress", turn_status="in_progress", required_actions=()
    ) == "TURN_RUNNING"
    assert classify_openai_session_state(
        session_status="requires_action",
        turn_status="waiting",
        required_actions=({"type": "function_call"},),
    ) == "REQUIRES_ACTION"
    assert classify_openai_session_state(
        session_status="idle", turn_status="completed", required_actions=()
    ) == "TURN_COMPLETED"


def test_create_session_uses_official_endpoint_harness_auth_and_persists_receipt():
    from app.database.openai_agents_repository import get_openai_agent_session_head

    transport = _FakeTransport([{
        "id": "sess_1",
        "status": "in_progress",
        "environment": {"id": "env_1"},
        "latest_turn": {"id": "turn_1", "status": "in_progress"},
    }])
    runtime = OpenAIAgentsRuntime(transport=transport)
    receipt = runtime.create_session(
        authorization_ref=_auth("dd2:create:1"),
        execution_id="dd2:create:1",
        agent_config={
            "model": "gpt-6.1-sol",
            "instructions": "bounded task",
            "reasoning": {"effort": "medium"},
            "tools": [],
            "multi_agent": {"enabled": False},
        },
        environment={"type": "none"},
        initial_input="hello",
        trace_refs=("task:1",),
    )
    assert transport.calls[0]["path"] == "/agents/sessions"
    assert transport.calls[0]["idempotency_key"] == "br-openai-session:dd2:create:1"
    assert receipt.state == "TURN_RUNNING"
    assert get_openai_agent_session_head("sess_1")["revision"] == 1

    with pytest.raises(PermissionError):
        runtime.create_session(
            authorization_ref="fabricated",
            execution_id="dd2:create:bad",
            agent_config={"model": "gpt-6.1-sol"},
            environment={"type": "none"},
            initial_input="x",
            trace_refs=(),
        )


def test_disconnect_recovery_retrieves_same_session_without_resending_input():
    from app.database.openai_agents_repository import persist_openai_agent_session_receipt

    seed = OpenAIAgentSessionReceipt.from_api(
        {"id": "sess_1", "status": "in_progress", "environment": {"id": "env_1"}},
        turn={"id": "turn_1", "status": "in_progress"},
        agent_model="gpt-6.1-sol",
        reasoning_effort="medium",
        multi_agent_enabled=False,
        subagent_count=0,
        tool_calls=(),
        artifacts=(),
        trace_refs=("seed:1",),
    )
    persist_openai_agent_session_receipt(seed)
    transport = _FakeTransport([
        TimeoutError("stream disconnected"),
        {
            "id": "sess_1",
            "status": "requires_action",
            "environment": {"id": "env_1"},
            "required_actions": [{
                "type": "function_call",
                "turn_id": "turn_1",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": {"x": 1},
            }],
        },
    ])
    runtime = OpenAIAgentsRuntime(transport=transport)
    with pytest.raises(TimeoutError):
        runtime.recover_same_session("sess_1", prior_turn_id="turn_1", trace_refs=("drop",))
    recovered = runtime.recover_same_session(
        "sess_1", prior_turn_id="turn_1", trace_refs=("recovery:1",)
    )
    assert recovered.session_id == "sess_1"
    assert recovered.state == "REQUIRES_ACTION"
    assert not any(call["method"] == "POST" for call in transport.calls)


def test_required_action_result_is_idempotent_and_202_is_not_completion():
    transport = _FakeTransport([{"_http_status": 202, "accepted": True}])
    runtime = OpenAIAgentsRuntime(transport=transport)
    first = runtime.submit_tool_result(
        authorization_ref=_auth("dd2:tool-result:1"),
        execution_id="dd2:tool-result:1",
        session_id="sess_1",
        turn_id="turn_1",
        call_id="call_1",
        tool_name="lookup",
        success=True,
        output='{"ok":true}',
        evidence_refs=("lookup:1",),
    )
    assert first["accepted"] is True
    assert first["completed"] is False
    assert transport.calls[0]["body"]["events"][0]["type"] == "agent.session.input.tool_result"

    duplicate = runtime.submit_tool_result(
        authorization_ref=_auth("dd2:tool-result:2"),
        execution_id="dd2:tool-result:2",
        session_id="sess_1",
        turn_id="turn_1",
        call_id="call_1",
        tool_name="lookup",
        success=True,
        output='{"ok":true}',
        evidence_refs=("lookup:1",),
    )
    assert duplicate["duplicate"] is True
    assert len(transport.calls) == 1


def test_receipt_persistence_is_revisioned_and_same_session_survives_restart():
    from app.database.openai_agents_repository import (
        get_openai_agent_session_head,
        persist_openai_agent_session_receipt,
    )

    first = OpenAIAgentSessionReceipt.from_api(
        {"id": "sess_1", "status": "in_progress", "environment": {"id": "env_1"}},
        turn={"id": "turn_1", "status": "in_progress"},
        agent_model="gpt-6.1-sol",
        reasoning_effort="medium",
        multi_agent_enabled=False,
        subagent_count=0,
        tool_calls=(),
        artifacts=(),
        trace_refs=("trace:1",),
        task_id="task-openai-1",
        attempt_id="attempt-openai-1",
        runtime_revision="dd2-restart-test",
        provider="openai",
        subagent_refs=("subagent:restart-a",),
    )
    persist_openai_agent_session_receipt(first)
    second = replace(
        first,
        state="REQUIRES_ACTION",
        required_actions=({"type": "function_call"},),
        revision=2,
    )
    persist_openai_agent_session_receipt(second, expected_current_revision=1)
    stored = get_openai_agent_session_head("sess_1")
    assert stored["revision"] == 2
    assert stored["state"] == "REQUIRES_ACTION"
    assert stored["task_id"] == "task-openai-1"
    assert stored["attempt_id"] == "attempt-openai-1"
    assert stored["runtime_revision"] == "dd2-restart-test"
    assert stored["provider"] == "openai"
    assert stored["subagent_refs"] == ["subagent:restart-a"]
    assert stored["artifact_refs"] == []


def test_multi_agent_only_for_independent_parallel_topology_default_ceiling_three():
    assert MAX_CONCURRENT_OPENAI_SUBAGENTS == 3
    plan = build_openai_subagent_plan(
        topology=_topology("PARALLEL_INDEPENDENT", branches=5),
        requested_subagents=5,
    )
    assert plan.max_concurrent_subagents == 3
    reduced = build_openai_subagent_plan(
        topology=_topology("PARALLEL_WITH_REDUCTION", branches=2),
        requested_subagents=3,
    )
    assert reduced.max_concurrent_subagents == 2
    for topology in ("SINGLE_AGENT", "SEQUENTIAL", "MAKER_CHECKER", "HIERARCHICAL"):
        assert build_openai_subagent_plan(
            topology=_topology(topology, branches=4),
            requested_subagents=3,
        ).enabled is False


def test_subagent_fanout_rejects_same_file_writes_and_shared_mutable_state():
    overlap = TaskTopologyAssessment(
        topology="PARALLEL_INDEPENDENT",
        reasons=("TEST_OVERLAP",),
        evidence={
            "parallelizable_branch_count": 3,
            "shared_mutable_state": False,
            "write_set_overlap": True,
        },
    )
    shared = TaskTopologyAssessment(
        topology="PARALLEL_INDEPENDENT",
        reasons=("TEST_SHARED",),
        evidence={
            "parallelizable_branch_count": 3,
            "shared_mutable_state": True,
            "write_set_overlap": False,
        },
    )
    assert build_openai_subagent_plan(
        topology=overlap, requested_subagents=3
    ).enabled is False
    assert build_openai_subagent_plan(
        topology=shared, requested_subagents=3
    ).enabled is False


def test_independent_research_may_fan_out_and_reduces_centrally():
    plan = build_openai_subagent_plan(
        topology=_topology("PARALLEL_INDEPENDENT", branches=2),
        requested_subagents=2,
    )
    assert plan.enabled is True
    assert plan.max_concurrent_subagents == 2
    root_result = build_task_result_envelope(
        mission_id="mission-openai-1",
        task_id="task-openai-1",
        capability_id="openai.agents.session",
        agent_id="openai-root-agent",
        skill_id=None,
        executor_binding="app.services.openai_agents_runtime_service.execute_openai_agents_session",
        status="COMPLETED",
        started_at="2026-09-30T10:00:00+00:00",
        completed_at="2026-09-30T10:00:01+00:00",
        elapsed_ms=1000,
        result={
            "summary": "central reduction complete",
            "evidence_refs": ["subagent-result:research-a", "subagent-result:research-b"],
            "artifact_refs": ["artifact:dd2:proof"],
        },
        source_task_ids=("research-a", "research-b"),
        authorization_id="auth-openai-lease",
    )
    assert root_result.source_task_ids == ("research-a", "research-b")
    assert set(root_result.evidence_refs) == {
        "subagent-result:research-a",
        "subagent-result:research-b",
    }


def test_tool_search_is_deferred_and_only_selected_namespaces_are_exposed():
    cfg = build_tool_search_configuration(
        namespaces=("github.read", "web.search", "youtube.analytics"),
        selected_namespaces=("web.search", "github.read"),
    )
    assert cfg == {
        "type": "tool_search",
        "defer_loading": True,
        "allowed_namespaces": ["web.search", "github.read"],
    }
    with pytest.raises(PermissionError):
        build_tool_search_configuration(
            namespaces=("github.read",),
            selected_namespaces=("github.write",),
        )


def test_skill_loading_is_selected_only_and_never_grants_authority():
    skills = (
        SelectedSkillSpec(
            skill_id="tdd", version="1", source="superpowers",
            instruction_hash="a" * 64, eligible=True, directory="/skills/tdd",
        ),
        SelectedSkillSpec(
            skill_id="deploy", version="1", source="br",
            instruction_hash="b" * 64, eligible=True,
            grants_authority=True, directory="/skills/deploy",
        ),
    )
    config = build_openai_agent_configuration(
        model_profile=gpt_6_1_sol_profile(),
        reasoning_effort="high",
        selected_skills=skills,
        tool_search=None,
        multi_agent_plan=build_openai_subagent_plan(
            topology=_topology("SINGLE_AGENT"), requested_subagents=0
        ),
    )
    assert [s["skill_id"] for s in config["skills"]] == ["tdd"]
    assert all(s["grants_authority"] is False for s in config["skills"])


def test_computer_use_requires_environment_and_task_lease_and_budget():
    decision = require_bounded_computer_use(
        environment_lease=_environment_lease(),
        task_lease=_task_lease(),
        requested_domain="github.com",
        requested_app="browser",
        requested_seconds=120,
    )
    assert decision["allowed"] is True
    assert decision["result_verification_required"] is True
    with pytest.raises(PermissionError):
        require_bounded_computer_use(
            environment_lease=replace(
                _environment_lease(), task_lease_ref="delegated-task:other"
            ),
            task_lease=_task_lease(),
            requested_domain="github.com",
            requested_app="browser",
            requested_seconds=120,
        )


def test_environment_lease_is_capacity_not_authority_and_durable():
    from app.database.openai_agents_repository import (
        get_agent_environment_lease,
        persist_agent_environment_lease,
    )
    lease = _environment_lease()
    assert lease.grants_task_authority is False
    persist_agent_environment_lease(lease)
    stored = get_agent_environment_lease(lease.lease_id)
    assert stored["task_lease_ref"] == lease.task_lease_ref
    assert stored["grants_task_authority"] is False


def test_model_profiles_truthful_but_not_routable_without_live_proof():
    sol = gpt_6_1_sol_profile()
    missing = classify_model_eligibility(
        model_id="gpt-6.1-sol", credentials_present=False, runtime_probe=None
    )
    assert missing.reason == "OPENAI_CREDENTIAL_UNAVAILABLE"
    proven = classify_model_eligibility(
        model_id="gpt-6.1-sol",
        credentials_present=True,
        runtime_probe={"status": "PASS", "model_id": "gpt-6.1-sol"},
    )
    assert proven.status == "FUNCTIONAL"


def test_registry_is_subordinate_and_sol_unproven_until_live_canary():
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

    agents=GLOBAL_CAPABILITY_REGISTRY.get("openai.agents.session")
    computer=GLOBAL_CAPABILITY_REGISTRY.get("openai.computer-use")
    sol=GLOBAL_CAPABILITY_REGISTRY.get("ai.provider.openai-gpt-6.1-sol")
    assert all(x is not None for x in (agents,computer,sol))
    for record in (agents,computer,sol):
        assert record.routing_authority=="NONE"
        assert record.publication_authority=="NONE"
        assert record.authority=="NONE"
        assert record.availability=="UNKNOWN/UNPROVEN"
    assert sol.model_id=="gpt-6.1-sol"


def test_stale_harness_authorization_cannot_create_second_agent_session():
    transport=_FakeTransport([
        {
            "id":"sess_once",
            "status":"in_progress",
            "environment":{"id":"env_once"},
            "latest_turn":{"id":"turn_once","status":"in_progress"},
            "required_actions":[],
        },
    ])
    runtime=OpenAIAgentsRuntime(transport=transport)
    auth=_auth("dd2:single-use")
    first=runtime.create_session(
        authorization_ref=auth,
        execution_id="dd2:single-use",
        agent_config={
            "model":"gpt-6.1-sol",
            "reasoning":{"effort":"medium"},
            "multi_agent":{"enabled":False},
        },
        environment={"type":"none"},
        initial_input="one",
        trace_refs=(),
    )
    assert first.session_id=="sess_once"
    with pytest.raises(PermissionError):
        runtime.create_session(
            authorization_ref=auth,
            execution_id="dd2:single-use",
            agent_config={
                "model":"gpt-6.1-sol",
                "reasoning":{"effort":"medium"},
                "multi_agent":{"enabled":False},
            },
            environment={"type":"none"},
            initial_input="two",
            trace_refs=(),
        )
    assert len(transport.calls)==1


def test_stdlib_http_transport_is_agents_only_and_redacts_secret_errors():
    from app.services.openai_agents_http_client import (
        OpenAIAgentsHTTPError,
        OpenAIAgentsHTTPTransport,
    )

    calls=[]
    def fake_request(method,url,*,headers,json_body=None,timeout_seconds=30):
        calls.append((method,url,headers,json_body,timeout_seconds))
        raise RuntimeError("Authorization Bearer sk-super-secret failed")

    transport=OpenAIAgentsHTTPTransport(
        api_key="sk-super-secret",
        request_json=fake_request,
    )
    with pytest.raises(PermissionError):
        transport.request("POST","/responses",body={})
    with pytest.raises(OpenAIAgentsHTTPError) as exc:
        transport.request("GET","/agents/sessions/s1")
    assert "sk-super-secret" not in str(exc.value)
    assert calls[0][1].endswith("/v1/agents/sessions/s1")


def test_registry_openai_records_have_zero_authority_before_live_proof():
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY

    for capability_id in (
        "openai.agents.session",
        "openai.computer-use",
        "ai.provider.openai-gpt-6.1-sol",
    ):
        record=GLOBAL_CAPABILITY_REGISTRY.get(capability_id)
        assert record is not None
        assert record.routing_authority=="NONE"
        assert record.publication_authority=="NONE"
        assert record.authority=="NONE"
        assert record.availability=="UNKNOWN/UNPROVEN"



def _execution_task_envelope(*, allowed_tools=("web.search",), expected_outputs=("artifact:dd2:proof",)) -> TaskEnvelope:
    return TaskEnvelope.from_mapping({
        "task_id": "task-openai-1",
        "mission_id": "mission-openai-1",
        "goal_id": "goal-openai-1",
        "capability_id": "openai.agents.session",
        "action": "EXECUTION",
        "objective": "Run bounded OpenAI agent work.",
        "task_class": "AGENTIC_EXECUTION",
        "functional_role": "SPECIALIST_EXECUTOR",
        "allowed_tools": list(allowed_tools),
        "allowed_side_effects": [],
        "expected_outputs": list(expected_outputs),
        "acceptance_criteria": ["Harness verifies typed result and required artifact"],
        "evidence_requirements": ["OpenAIAgentSessionReceipt/v1", "TaskResultEnvelope/v1"],
        "time_budget_seconds": 600,
        "cost_budget": 5.0,
        "tool_budget": 20,
        "retry_budget": 2,
        "risk_side_effect_class": "READ_ONLY",
    })


def _execution_responsibility(*, allowed_tools=("web.search",), allowed_skills=("tdd",)) -> PersistentResponsibility:
    research_policy = ProactiveResearchPolicy.from_mapping({
        "policy_id": "openai-dd2-read-only",
        "mode": "READ_ONLY",
        "allowed_actions": ["READ", "SEARCH", "INSPECT", "COMPARE", "RETRIEVE", "SUMMARIZE"],
        "allowed_sources": ["PUBLIC_WEB"],
        "max_items_per_wake": 20,
    })
    time_budget = PersistentWorkTimeBudget.from_mapping({
        "maximum_wall_clock_per_wake_seconds": 600,
        "maximum_total_active_time_per_day_seconds": 3600,
        "maximum_agent_turns": 20,
        "maximum_semantic_calls": 12,
        "maximum_provider_calls": 12,
        "maximum_tool_calls": 30,
        "maximum_subagents": 3,
        "maximum_subagent_time_seconds": 900,
        "maximum_retries": 3,
        "maximum_external_tool_time_seconds": 1200,
        "maximum_cost_per_wake": 5.0,
        "maximum_cost_per_day": 20.0,
    })
    return PersistentResponsibility.from_mapping({
        "responsibility_id": "OPENAI_DD2_EXECUTION",
        "owner": "BR_OWNER",
        "name": "OpenAI DD2 Execution",
        "description": "Bound subordinate OpenAI runtime execution.",
        "business_outcome": "Produce verified typed task results.",
        "domain": "agent-runtime",
        "task_classes": ["AGENTIC_EXECUTION"],
        "priority": 80,
        "enabled": True,
        "created_at": "2026-09-30T10:00:00+00:00",
        "updated_at": "2026-09-30T10:00:00+00:00",
        "trigger_policy": {"mode": "HARNESS_ONLY"},
        "proactive_research_policy": research_policy.to_dict(),
        "allowed_sources": ["PUBLIC_WEB"],
        "allowed_tools": list(allowed_tools),
        "allowed_skills": list(allowed_skills),
        "allowed_agents": ["openai-root-agent"],
        "allowed_side_effects": [],
        "approval_policy": {"side_effects": "HARNESS_AUTHORIZATION_REQUIRED"},
        "risk_class": "READ_ONLY_BACKGROUND",
        "time_budget": time_budget.to_dict(),
        "compute_budget": {"max_parallel_tasks": 3},
        "cost_budget": {"max_cost_per_wake_usd": 5.0, "max_cost_per_day_usd": 20.0},
        "observation_interval": {"seconds": 900},
        "event_triggers": ["harness.task.authorized"],
        "wake_conditions": ["HARNESS_TASK"],
        "context_policy": {"carry": ["artifact_refs"]},
        "memory_policy": {"write": "EVIDENCE_BOUND_ONLY"},
        "artifact_policy": {"typed_only": True},
        "success_metrics": ["verified_task_results"],
        "failure_conditions": ["AUTHORITY_ESCAPE"],
        "escalation_policy": {"on_risk": "HAND_OFF_TO_HUMAN"},
        "pause_policy": {"owner_can_pause": True},
        "current_revision": 1,
        "status": "DORMANT",
    })


def _allow_rule(target: str = "web.search") -> AgentCustomRule:
    return AgentCustomRule.from_mapping({
        "rule_id": "rule-openai-dd2-allow",
        "responsibility_id": "OPENAI_DD2_EXECUTION",
        "effect": "ALLOW",
        "action": "TOOL_USE",
        "target": target,
        "risk_class": "READ_ONLY",
        "conditions": {},
        "revision": 1,
        "status": "ACTIVE",
    })


def test_session_receipt_has_complete_durable_execution_identity_and_no_runtime_self_import(monkeypatch):
    monkeypatch.setitem(sys.modules, "app.services.openai_agents_runtime_service", None)
    receipt = OpenAIAgentSessionReceipt.from_api(
        {"id": "sess_identity", "status": "idle", "environment": {"id": "env_identity"}},
        turn={"id": "turn_identity", "status": "completed"},
        task_id="task-openai-1",
        attempt_id="attempt-openai-1",
        runtime_revision="dd2-test",
        provider="openai",
        agent_model="gpt-6.1-sol",
        reasoning_effort="high",
        multi_agent_enabled=True,
        subagent_count=2,
        subagent_refs=("subagent:1", "subagent:2"),
        tool_calls=({"call_id": "call-1", "name": "web.search"},),
        artifacts=({"id": "artifact:dd2:proof"},),
        trace_refs=("trace:identity",),
    )
    assert receipt.task_id == "task-openai-1"
    assert receipt.attempt_id == "attempt-openai-1"
    assert receipt.runtime_revision == "dd2-test"
    assert receipt.provider == "openai"
    assert receipt.model == "gpt-6.1-sol"
    assert receipt.subagent_refs == ("subagent:1", "subagent:2")
    assert receipt.artifact_refs == ("artifact:dd2:proof",)
    assert receipt.state == "TURN_COMPLETED"


def test_openai_execution_scope_is_intersection_not_union():
    task = _execution_task_envelope(allowed_tools=("web.search", "github.write"))
    lease = replace(
        _task_lease(),
        allowed_tools=("web.search", "github.write"),
        capability_ids=("openai.agents.session",),
    )
    responsibility = _execution_responsibility(allowed_tools=("web.search",))
    decision = authorize_openai_execution_scope(
        task_envelope=task,
        task_lease=lease,
        responsibility=responsibility,
        custom_rules=(_allow_rule("web.search"),),
        requested_tools=("web.search",),
        requested_skills=("tdd",),
        risk_class="READ_ONLY",
    )
    assert decision["allowed"] is True
    assert decision["allowed_tools"] == ["web.search"]
    assert decision["allowed_skills"] == ["tdd"]
    assert decision["grants_authority"] is False

    with pytest.raises(PermissionError):
        authorize_openai_execution_scope(
            task_envelope=task,
            task_lease=lease,
            responsibility=responsibility,
            custom_rules=(_allow_rule("github.write"),),
            requested_tools=("github.write",),
            requested_skills=("tdd",),
            risk_class="READ_ONLY",
        )


def test_harness_verification_requires_task_result_envelope_and_required_artifact():
    completed = OpenAIAgentSessionReceipt.from_api(
        {"id": "sess_verify", "status": "idle", "environment": {"id": "env_verify"}},
        turn={"id": "turn_verify", "status": "completed"},
        task_id="task-openai-1",
        attempt_id="attempt-openai-1",
        runtime_revision="dd2-test",
        provider="openai",
        agent_model="gpt-6.1-sol",
        reasoning_effort="high",
        multi_agent_enabled=False,
        subagent_count=0,
        subagent_refs=(),
        tool_calls=(),
        artifacts=({"id": "artifact:dd2:proof"},),
        trace_refs=("trace:verify",),
    )
    task = _execution_task_envelope(expected_outputs=("artifact:dd2:proof",))
    result = build_task_result_envelope(
        mission_id=task.mission_id,
        task_id=task.task_id,
        capability_id=task.capability_id,
        agent_id="openai-root-agent",
        skill_id=None,
        executor_binding="app.services.openai_agents_runtime_service.execute_openai_agents_session",
        status="COMPLETED",
        started_at=completed.created_at,
        completed_at=completed.updated_at,
        elapsed_ms=1.0,
        result={
            "summary": "bounded result",
            "artifact_refs": list(completed.artifact_refs),
            "evidence_refs": list(completed.trace_refs),
        },
        source_task_ids=(),
        authorization_id="auth-openai-lease",
    )
    verified = verify_openai_task_completion(
        completed,
        task_envelope=task,
        task_result=result,
        verification_ref="harness-verification:dd2:test",
    )
    assert verified.state == "TASK_VERIFIED"

    missing = build_task_result_envelope(
        mission_id=task.mission_id,
        task_id=task.task_id,
        capability_id=task.capability_id,
        agent_id="openai-root-agent",
        skill_id=None,
        executor_binding="app.services.openai_agents_runtime_service.execute_openai_agents_session",
        status="COMPLETED",
        started_at=completed.created_at,
        completed_at=completed.updated_at,
        elapsed_ms=1.0,
        result={"summary": "missing required artifact", "artifact_refs": []},
        source_task_ids=(),
        authorization_id="auth-openai-lease",
    )
    with pytest.raises(PermissionError, match="required output"):
        verify_openai_task_completion(
            completed,
            task_envelope=task,
            task_result=missing,
            verification_ref="harness-verification:dd2:test:missing",
        )



def test_dd2_secret_detector_does_not_treat_task_id_as_openai_secret():
    from scripts.openai_agents_dd2_operational_proof import _contains_openai_secret

    assert _contains_openai_secret({"task_id": "task-dd2-proof"}) is False
    assert _contains_openai_secret({"token": "sk-super-secret"}) is True



def test_model_selection_is_registry_driven_not_sol_hardcoded():
    class _Registry:
        def __init__(self, records):
            self._records = tuple(records)

        def all(self):
            return self._records

    alternate = SimpleNamespace(
        capability_type="PROVIDER",
        provider_id="openai",
        model_id="gpt-openai-alternate-test",
    )
    registry = _Registry((alternate,))
    selected = require_registered_openai_model(
        "gpt-openai-alternate-test",
        registry=registry,
    )
    assert selected is alternate
    with pytest.raises(PermissionError):
        require_registered_openai_model("gpt-6.1-sol", registry=registry)


def test_canonical_openai_runtime_imports_cleanly_in_fresh_process():
    code = (
        "import app.services.openai_agents_contracts as c; "
        "import app.services.openai_agents_runtime_service as r; "
        "assert c.OpenAIAgentSessionReceipt.__name__ == 'OpenAIAgentSessionReceipt'; "
        "assert r.OpenAIAgentsRuntime.__name__ == 'OpenAIAgentsRuntime'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr



def test_registry_session_binding_is_harness_adapter_compatible():
    from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
    from app.services.harness_executor_contract_service import (
        registry_executor_is_task_adapter_compatible,
    )

    session = GLOBAL_CAPABILITY_REGISTRY.get("openai.agents.session")
    computer = GLOBAL_CAPABILITY_REGISTRY.get("openai.computer-use")
    sol = GLOBAL_CAPABILITY_REGISTRY.get("ai.provider.openai-gpt-6.1-sol")

    assert session is not None
    assert session.executor_binding == (
        "app.services.openai_agents_runtime_service.execute_openai_agents_session"
    )
    assert registry_executor_is_task_adapter_compatible(session.executor_binding) is True

    assert computer is not None
    assert computer.availability == "UNKNOWN/UNPROVEN"
    assert computer.executor_binding is None

    assert sol is not None
    assert sol.availability == "UNKNOWN/UNPROVEN"
    assert sol.executor_binding is None
