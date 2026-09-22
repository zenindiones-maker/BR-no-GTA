from __future__ import annotations

from dataclasses import replace

import pytest

from app.services import harness_adaptive_planning_service as adaptive
from app.services.capability_health_service import (
    CapabilityHealth,
    BLOCKED,
    HEALTHY,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.harness_collaboration_service import (
    TaskEnvelope,
    build_collaboration_plan,
)
from app.services.harness_mission_execution_router import (
    select_mission_execution_route,
)
from app.services.hermes_multiagent.contracts import (
    DelegationEnvelope,
    TypedHandoff,
)
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.hermes_multiagent.capability_broker import (
    DelegatedCapabilityFailure,
    HermesHarnessCapabilityBroker,
)
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from scripts.audit_harness_ecosystem import audit


def _competence(
    capability_id: str,
    *,
    tested: int,
    success_rate: float,
    task_class: str = "bounded-development",
) -> dict:
    return {
        "capability_id": capability_id,
        "task_class": task_class,
        "version": "1",
        "tested_cases": tested,
        "success_rate": success_rate,
        "failure_rate": max(0.0, 1.0 - success_rate),
        "human_correction_rate": 0.0,
        "retry_rate": 0.0,
        "mean_latency_seconds": 10.0,
        "mean_cost": 0.0,
        "freshness_score": 1.0,
        "confidence": 0.9,
        "status": "ACTIVE",
    }


def test_canonical_task_envelope_carries_scope_budget_review_and_idempotency():
    task = TaskEnvelope.from_mapping({
        "task_id": "inspect-cache",
        "capability_id": "gta6.knowledge.retrieve",
        "authorized_action": "RESEARCH",
        "objective": "Inspect relevant canonical knowledge without mutation",
        "task_class": "readonly-analysis",
        "required_capability_description": "bounded canonical knowledge retrieval",
        "dependencies": [],
        "input_refs": ["artifact:input-1"],
        "expected_output": "KnowledgeEvidence",
        "acceptance_criteria": ["return provenance", "stay bounded"],
        "read_scope": [],
        "write_scope": [],
        "allowed_tools": [],
        "allowed_side_effects": [],
        "forbidden_side_effects": ["publication", "canonical_memory_write"],
        "time_budget_seconds": 90,
        "cost_budget": 0.0,
        "context_budget_bytes": 8192,
        "tool_budget": 4,
        "retry_budget": 1,
        "evidence_contract": "claim/evidence provenance",
        "review_policy": "NONE",
        "risk_side_effect_class": "READ_ONLY",
        "human_gate_policy": "NONE",
    })
    first = build_collaboration_plan(
        mission_id="mission-task-envelope",
        goal_id="goal-task-envelope",
        tasks=[task],
    )
    second = build_collaboration_plan(
        mission_id="mission-task-envelope",
        goal_id="goal-task-envelope",
        tasks=[task],
    )
    routed = first.tasks[0]
    assert routed.authorized_action == "RESEARCH"
    assert routed.task_class == "readonly-analysis"
    assert routed.acceptance_criteria == ("return provenance", "stay bounded")
    assert routed.context_budget_bytes == 8192
    assert routed.tool_budget == 4
    assert routed.retry_budget == 1
    assert routed.review_policy == "NONE"
    assert routed.risk_side_effect_class == "READ_ONLY"
    assert routed.idempotency_key.startswith("task:")
    assert routed.idempotency_key == second.tasks[0].idempotency_key
    assert routed.mission_id == "mission-task-envelope"
    assert routed.goal_id == "goal-task-envelope"


def test_competence_confidence_adjustment_prefers_robust_history_over_one_of_one():
    record = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.bounded-development"
    )
    assert record is not None
    requirement = {
        "task_class": "bounded-development",
        "task_id": "bounded-change",
    }
    weak_context = {
        "competence_evidence": [
            _competence(record.capability_id, tested=1, success_rate=1.0)
        ]
    }
    strong_context = {
        "competence_evidence": [
            _competence(record.capability_id, tested=50, success_rate=46 / 50)
        ]
    }
    weak_score, _, weak = adaptive._competence_score(
        record,
        requirement=requirement,
        context=weak_context,
    )
    strong_score, _, strong = adaptive._competence_score(
        record,
        requirement=requirement,
        context=strong_context,
    )
    assert strong_score > weak_score
    assert strong["wilson_success_lower_bound"] > weak["wilson_success_lower_bound"]
    assert strong["sample_strength"] > weak["sample_strength"]
    assert weak["sample_size_interpretation"] == "LOW_CONFIDENCE"
    assert strong["sample_size_interpretation"] == "ESTABLISHED"


def test_selector_excludes_blocked_health_and_records_health_evidence(monkeypatch):
    primary = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.readonly-analysis"
    )
    alternate = GLOBAL_CAPABILITY_REGISTRY.get(
        "agent-office.codex.bounded-development"
    )
    assert primary is not None and alternate is not None

    class FakeRegistry:
        def discover(self, **_kwargs):
            return [
                {"capability_id": primary.capability_id},
                {"capability_id": alternate.capability_id},
            ]

        def get(self, capability_id):
            return {
                primary.capability_id: primary,
                alternate.capability_id: alternate,
            }.get(capability_id)

    def health(capability_id: str):
        state = BLOCKED if capability_id == primary.capability_id else HEALTHY
        return CapabilityHealth(
            capability_id=capability_id,
            state=state,
            reason="test health",
            retry_allowed=state == HEALTHY,
            confidence=0.95,
            sample_size=20,
            last_success_at=None,
            last_failure_at=None,
            evidence_refs=("test:health",),
            source="TEST_CAPTURED",
        )

    monkeypatch.setattr(adaptive, "GLOBAL_CAPABILITY_REGISTRY", FakeRegistry())
    monkeypatch.setattr(adaptive, "capability_health", health)

    selected, _, avoided, evidence = adaptive.select_capability_for_requirement(
        {
            "task_id": "readonly",
            "task_class": "readonly-analysis",
            "action": "DEVELOPMENT",
            "query": "readonly source code analysis",
            "objective": "analyze without mutation",
            "candidate_capability_ids": [
                primary.capability_id,
                alternate.capability_id,
            ],
            "risk_side_effect_class": "READ_ONLY",
        },
        context={"competence_evidence": [], "relevant_failure_memories": []},
        used=set(),
    )
    assert selected == alternate.capability_id
    assert any(primary.capability_id in item for item in avoided)
    assert evidence["health_evidence"]["state"] == HEALTHY
    assert evidence["top_candidates"][0]["health_state"] == HEALTHY


def test_registry_execution_contract_is_single_and_exposes_execution_metadata():
    records = [
        record
        for record in GLOBAL_CAPABILITY_REGISTRY.all()
        if record.capability_type != "PROVIDER" and record.execution_enabled
    ]
    assert records
    for record in records:
        assert isinstance(record.supports_parallelism, bool)
        assert isinstance(record.supports_retry, bool)
        assert isinstance(record.supports_resume, bool)
        assert isinstance(record.supports_review, bool)
        assert record.side_effect_class
        assert record.health_policy
    assert len({
        record.capability_id for record in GLOBAL_CAPABILITY_REGISTRY.all()
    }) == len(GLOBAL_CAPABILITY_REGISTRY.all())


def test_ecosystem_has_no_second_capability_authority():
    result = audit()
    assert result["authority"] == "DEEPSEEK_HARNESS"
    assert result["NO_DUPLICATE_AUTHORITY"] is True
    assert all(
        row["AUTHORITY_LEVEL"] in {"INHERITED", "NONE", "DELEGATED_ONLY"}
        for row in result["capabilities"]
    )


def _mission_plan_for_route(*tasks: TaskEnvelope, mission_class: str = "OPEN_SEMANTIC"):
    collaboration = build_collaboration_plan(
        mission_id="mission-route-test",
        goal_id="goal-route-test",
        tasks=list(tasks),
    )
    return {
        "authority": "DEEPSEEK_HARNESS",
        "goal": {
            "goal_id": "goal-route-test",
            "human_goal": "route this work",
            "mission_class": mission_class,
        },
        "collaboration_plan": collaboration.to_dict(),
    }


def test_topology_simple_task_avoids_hermes():
    plan = _mission_plan_for_route(TaskEnvelope(
        task_id="retrieve",
        capability_id="gta6.knowledge.retrieve",
        action="RESEARCH",
        objective="Retrieve bounded existing GTA6 knowledge",
        task_class="readonly-retrieval",
        expected_output="KnowledgeEvidence",
        review_policy="NONE",
    ))
    route = select_mission_execution_route(plan)
    assert route.runtime == "DIRECT_CAPABILITY"
    assert route.hermes_used is False
    assert route.coordination_benefit is False


def test_topology_parallel_readonly_uses_light_hermes_coordination():
    plan = _mission_plan_for_route(
        TaskEnvelope(
            task_id="retrieve-a",
            capability_id="gta6.knowledge.retrieve",
            action="RESEARCH",
            objective="Retrieve knowledge A",
            task_class="readonly-retrieval",
            expected_output="KnowledgeEvidence",
            review_policy="NONE",
        ),
        TaskEnvelope(
            task_id="retrieve-b",
            capability_id="gta6.knowledge.retrieve",
            action="RESEARCH",
            objective="Retrieve knowledge B",
            task_class="readonly-retrieval",
            expected_output="KnowledgeEvidence",
            review_policy="NONE",
        ),
    )
    route = select_mission_execution_route(plan)
    assert route.runtime == "HERMES_COLLABORATION"
    assert route.hermes_used is True
    assert route.coordination_benefit is True
    assert route.durable is False


def test_topology_dependency_or_review_uses_durable_hermes_kanban():
    plan = _mission_plan_for_route(
        TaskEnvelope(
            task_id="analyze",
            capability_id="agent-office.codex.readonly-analysis",
            action="DEVELOPMENT",
            objective="Analyze a bounded system problem",
            task_class="root-cause-analysis",
            expected_output="AnalysisEvidence",
            review_policy="NONE",
        ),
        TaskEnvelope(
            task_id="change",
            capability_id="agent-office.codex.bounded-development",
            action="DEVELOPMENT",
            objective="Create a bounded candidate",
            task_class="bounded-development",
            dependencies=("analyze",),
            expected_output="CandidateEvidence",
            write_scope=("app",),
            review_policy="INDEPENDENT_REQUIRED",
            risk_side_effect_class="BOUNDED_MUTATION",
        ),
    )
    route = select_mission_execution_route(plan)
    assert route.runtime == "HERMES_KANBAN"
    assert route.hermes_used is True
    assert route.durable is True
    assert route.has_dependencies is True


class _FakeHermesBoard:
    def __init__(self):
        self.created = []
        self.comments = []

    def create_task(self, **kwargs):
        task_id = f"board-{len(self.created) + 1}"
        self.created.append({"id": task_id, **kwargs})
        return task_id

    def comment(self, task_id, *, author, body):
        self.comments.append({"task_id": task_id, "author": author, "body": body})
        return len(self.comments)


def _delegation_fixture():
    plan = build_collaboration_plan(
        mission_id="mission-delegation-envelope",
        goal_id="goal-delegation-envelope",
        tasks=[
            TaskEnvelope(
                task_id="profile",
                capability_id="agent-office.codex.readonly-analysis",
                action="DEVELOPMENT",
                objective="profile application performance bottleneck",
                task_class="performance-profiling",
                expected_output="ProfileEvidence",
                read_scope=("app", "scripts"),
                write_scope=(),
                allowed_tools=("git", "python", "pytest", "codex", "rg", "cat"),
                allowed_side_effects=(
                    "ephemeral worktree",
                    "structured runtime artifact",
                ),
                time_budget_seconds=300,
                context_budget_bytes=16384,
                tool_budget=12,
                retry_budget=1,
                review_policy="NONE",
            )
        ],
    )
    parent = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:collaboration.hermes.execute",
        harness_decision_id="decision-delegation-envelope",
        execution_id="execution-delegation-envelope",
        lineage={"test": "delegation-envelope"},
    )
    envelope = DelegationEnvelope.from_plan(
        collaboration_plan=plan,
        harness_decision_id="decision-delegation-envelope",
        authorization_id=parent.authorization_id,
        base_sha="a" * 40,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(minutes=15)
        ).isoformat(),
        max_child_depth=2,
        max_child_tasks=3,
    )
    return plan, parent, envelope


def test_delegation_envelope_blocks_authority_scope_and_budget_expansion():
    _plan, parent_auth, envelope = _delegation_fixture()
    try:
        allowed = envelope.validate_child_task(
            parent_task_id="profile",
            child={
                "task_id": "profile-python",
                "capability_id": "agent-office.codex.readonly-analysis",
                "authorized_action": "DEVELOPMENT",
                "objective": "profile python performance bottleneck",
                "read_scope": ["app"],
                "write_scope": [],
                "allowed_side_effects": ["ephemeral worktree"],
                "time_budget_seconds": 120,
                "context_budget_bytes": 8192,
                "tool_budget": 6,
                "retry_budget": 1,
            },
            depth=1,
            existing_child_count=0,
        )
        assert allowed.read_scope == ("app",)
        assert allowed.write_scope == ()
        assert allowed.action == "DEVELOPMENT"

        for bad in (
            {
                "task_id": "bad-action",
                "capability_id": "agent-office.codex.readonly-analysis",
                "authorized_action": "PUBLICATION",
                "objective": "profile python performance bottleneck",
            },
            {
                "task_id": "bad-write",
                "capability_id": "agent-office.codex.readonly-analysis",
                "authorized_action": "DEVELOPMENT",
                "objective": "profile python performance bottleneck",
                "write_scope": ["app"],
            },
            {
                "task_id": "bad-budget",
                "capability_id": "agent-office.codex.readonly-analysis",
                "authorized_action": "DEVELOPMENT",
                "objective": "profile python performance bottleneck",
                "time_budget_seconds": 301,
            },
        ):
            with pytest.raises(PermissionError):
                envelope.validate_child_task(
                    parent_task_id="profile",
                    child=bad,
                    depth=1,
                    existing_child_count=0,
                )
    finally:
        consume_harness_authorization(parent_auth)


def test_hermes_child_proposal_routes_through_harness_and_is_idempotent():
    _plan, parent_auth, envelope = _delegation_fixture()
    board = _FakeHermesBoard()
    try:
        broker = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir="/tmp/hermes-delegation-plane-test",
        )
        child = {
            "task_id": "profile-python",
            "capability_id": "agent-office.codex.readonly-analysis",
            "authorized_action": "DEVELOPMENT",
            "objective": "profile python performance bottleneck",
            "read_scope": ["app"],
            "write_scope": [],
            "allowed_side_effects": ["ephemeral worktree"],
            "time_budget_seconds": 120,
            "context_budget_bytes": 8192,
            "tool_budget": 6,
            "retry_budget": 1,
        }
        first = broker.propose_child_task(
            parent_task_id="profile",
            child=child,
        )
        assert first["status"] == "AUTHORIZED"
        assert first["HERMES_SUBDELEGATION_WITHIN_ENVELOPE"] == "PASS"
        assert first["HERMES_AUTHORITY_EXPANSION"] == "NO"
        routed = first["task"]
        assert routed["routing_id"]
        assert routed["selected_executor_binding"]
        assert routed["idempotency_key"].startswith("child:")
        assert len(board.created) == 1

        second = broker.propose_child_task(
            parent_task_id="profile",
            child={**child, "idempotency_key": routed["idempotency_key"]},
        )
        assert second["status"] == "REUSED"
        assert second["DUPLICATE_AGENT_EXECUTION_AVOIDED"] == "PASS"
        assert len(board.created) == 1
    finally:
        consume_harness_authorization(parent_auth)


def test_typed_handoff_has_bounded_cross_agent_lineage():
    handoff = TypedHandoff(
        from_task_id="analyze",
        to_task_id="review",
        evidence_refs=("artifact:analysis.json",),
        result_ref="artifact:analysis.json",
        output_contract="AnalysisEvidence",
        summary="Root cause isolated with bounded evidence.",
        acceptance_state="ACCEPTED_FOR_DEPENDENCY",
        artifact_lineage={
            "sha256": "b" * 64,
            "authorization_id": "auth-1",
            "routing_id": "route-1",
        },
        producer_capability_id="agent-office.codex.readonly-analysis",
        producer_agent_id="codex-readonly",
        producer_skill_id=None,
        producer_version="1",
        observed_at=datetime.now(timezone.utc).isoformat(),
    )
    assert handoff.to_dict()["evidence_refs"] == ("artifact:analysis.json",)
    with pytest.raises(ValueError):
        TypedHandoff(
            from_task_id="a",
            to_task_id="b",
            evidence_refs=("artifact:x",),
            result_ref="artifact:x",
            output_contract="x",
            summary="x" * 5000,
            acceptance_state="ACCEPTED_FOR_DEPENDENCY",
            artifact_lineage={},
            producer_capability_id="x",
            producer_agent_id=None,
            producer_skill_id=None,
            producer_version="1",
            observed_at=datetime.now(timezone.utc).isoformat(),
        )


def test_execution_idempotency_reuses_persisted_result_after_broker_restart(
    monkeypatch,
    tmp_path,
):
    _plan, parent_auth, envelope = _delegation_fixture()
    board = _FakeHermesBoard()
    calls = []

    def fake_execute(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            result={"status": "PASS", "evidence": "captured"},
            elapsed_seconds=0.01,
        )

    try:
        broker = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir=tmp_path,
        )
        monkeypatch.setattr(broker.adapter, "execute", fake_execute)
        first = broker.execute_delegated_capability(
            task_id="profile",
            capability_id="agent-office.codex.readonly-analysis",
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert first["executed"] is True
        assert first["reused"] is False
        assert len(calls) == 1

        same = broker.execute_delegated_capability(
            task_id="profile",
            capability_id="agent-office.codex.readonly-analysis",
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert same["executed"] is False
        assert same["reused"] is True
        assert same["DUPLICATE_AGENT_EXECUTION_AVOIDED"] == "PASS"
        assert len(calls) == 1

        resumed = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir=tmp_path,
        )
        monkeypatch.setattr(resumed.adapter, "execute", fake_execute)
        after_restart = resumed.execute_delegated_capability(
            task_id="profile",
            capability_id="agent-office.codex.readonly-analysis",
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert after_restart["reused"] is True
        assert after_restart["DUPLICATE_AGENT_EXECUTION_AVOIDED"] == "PASS"
        assert len(calls) == 1
    finally:
        consume_harness_authorization(parent_auth)


def test_retry_stays_same_capability_and_exhaustion_requires_harness_replan(
    monkeypatch,
    tmp_path,
):
    _plan, parent_auth, envelope = _delegation_fixture()
    board = _FakeHermesBoard()
    attempts = {"count": 0}

    def fail_then_pass(**_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("captured transient failure")
        return SimpleNamespace(
            result={"status": "PASS"},
            elapsed_seconds=0.01,
        )

    try:
        broker = HermesHarnessCapabilityBroker(
            spec=envelope,
            parent_authorization=parent_auth,
            board=board,
            task_mapping={"profile": "board-parent"},
            artifact_dir=tmp_path,
        )
        monkeypatch.setattr(broker.adapter, "execute", fail_then_pass)
        with pytest.raises(DelegatedCapabilityFailure) as raised:
            broker.execute_delegated_capability(
                task_id="profile",
                capability_id="agent-office.codex.readonly-analysis",
                payload={"goal_id": envelope.goal_id, "task": "profile safely"},
            )
        failure = raised.value
        assert failure.retry_allowed is True
        assert failure.requires_harness_replan is False

        retried = broker.retry_delegated_capability(
            failure=failure,
            payload={"goal_id": envelope.goal_id, "task": "profile safely"},
        )
        assert retried["executed"] is True
        assert attempts["count"] == 2

        with pytest.raises(PermissionError, match="cannot reroute"):
            broker.execute_delegated_capability(
                task_id="profile",
                capability_id="system.improvement.propose",
                payload={},
            )
    finally:
        consume_harness_authorization(parent_auth)

    # Separate mission proves exhaustion becomes a structured replan request.
    _plan2, parent_auth2, envelope2 = _delegation_fixture()
    board2 = _FakeHermesBoard()

    def always_fail(**_kwargs):
        raise RuntimeError("persistent captured failure")

    try:
        broker2 = HermesHarnessCapabilityBroker(
            spec=envelope2,
            parent_authorization=parent_auth2,
            board=board2,
            task_mapping={"profile": "board-parent"},
            artifact_dir=tmp_path / "exhausted",
        )
        monkeypatch.setattr(broker2.adapter, "execute", always_fail)
        with pytest.raises(DelegatedCapabilityFailure) as first_error:
            broker2.execute_delegated_capability(
                task_id="profile",
                capability_id="agent-office.codex.readonly-analysis",
                payload={"goal_id": envelope2.goal_id, "task": "profile safely"},
            )
        with pytest.raises(DelegatedCapabilityFailure) as second_error:
            broker2.retry_delegated_capability(
                failure=first_error.value,
                payload={"goal_id": envelope2.goal_id, "task": "profile safely"},
            )
        exhausted = second_error.value
        assert exhausted.retry_allowed is False
        assert exhausted.requires_harness_replan is True
        assert broker2.audit_snapshot()[-1]["requires_harness_replan"] is True
        with pytest.raises(PermissionError, match="requires DeepSeek Harness replan"):
            broker2.retry_delegated_capability(
                failure=exhausted,
                payload={"goal_id": envelope2.goal_id, "task": "profile safely"},
            )
    finally:
        consume_harness_authorization(parent_auth2)
