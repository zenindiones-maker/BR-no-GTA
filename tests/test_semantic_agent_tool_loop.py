from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database.schema import initialize_schema
from app.services.harness_authorization_service import (
    consume_harness_authorization,
    issue_harness_authorization,
)
from app.services.harness_collaboration_service import (
    TaskEnvelope,
    build_collaboration_plan,
)
from app.services.capability_execution_contract_service import (
    CAN_SEMANTIC_REASONING,
)
from app.services.global_capability_registry import GLOBAL_CAPABILITY_REGISTRY
from app.services.hermes_multiagent.capability_broker import (
    DelegatedCapabilityFailure,
    HermesHarnessCapabilityBroker,
)
from app.services.hermes_multiagent.contracts import DelegationEnvelope
from app.services.harness_routing_policy_service import RoutingPolicyError
from app.services.semantic_tool_loop_service import (
    TOOL_REQUEST_SCHEMA,
    build_tool_result_envelope,
    extract_tool_request,
    utcnow,
)
from app.services.agent_session_service import AgentSessionRuntime


class _Board:
    def comment(self, task_id, *, author, body):
        return 1


def _fixture(tmp_path: Path, *, tool_budget: int = 2):
    initialize_schema()
    plan = build_collaboration_plan(
        mission_id="mission-semantic-tool-loop",
        goal_id="goal-semantic-tool-loop",
        tasks=[
            TaskEnvelope(
                task_id="task-02",
                capability_id="addy:debugging-and-error-recovery",
                action="DEVELOPMENT",
                objective="Diagnose the observed Registry selection failure.",
                task_class="incident-diagnosis",
                functional_role="DIAGNOSIS",
                expected_output="IncidentDiagnosisEvidence",
                required_capability_description=(
                    "semantic read-only incident diagnosis"
                ),
                required_operations=(
                    "CAN_SEMANTIC_REASONING",
                    "CAN_CONSUME_ARTIFACT_REFS",
                    "CAN_PRODUCE_ARTIFACT_REFS",
                ),
                read_scope=(),
                write_scope=(),
                allowed_tools=(),
                allowed_side_effects=(),
                time_budget_seconds=120,
                context_budget_bytes=16000,
                tool_budget=tool_budget,
                retry_budget=0,
                review_policy="NONE",
                risk_side_effect_class="READ_ONLY",
            ),
        ],
    )
    parent = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="capability:collaboration.hermes.execute",
        harness_decision_id="decision-semantic-tool-loop",
        execution_id="execution-semantic-tool-loop",
        lineage={"test": "semantic-tool-loop"},
    )
    envelope = DelegationEnvelope.from_plan(
        collaboration_plan=plan,
        harness_decision_id=parent.harness_decision_id,
        authorization_id=parent.authorization_id,
        base_sha="a" * 40,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(minutes=10)
        ).isoformat(),
    )
    packet = tmp_path / "incident-evidence-packet.json"
    packet.write_text(
        json.dumps({
            "schema": "real-incident-evidence-packet/v1",
            "incident": {
                "failure_class": "PLANNER_CONTRACT_REGISTRY_SELECTION_FAILURE",
                "error": (
                    "no healthy Registry capability for "
                    "task_class=production-planning"
                ),
            },
        }),
        encoding="utf-8",
    )
    context = {
        "mission_id": envelope.mission_id,
        "task_id": "task-02",
        "goal_id": envelope.goal_id,
        "evidence_refs": ["artifact:incident-evidence-packet.json"],
        "parent_handoffs": [],
    }
    broker = HermesHarnessCapabilityBroker(
        spec=envelope,
        parent_authorization=parent,
        board=_Board(),
        task_mapping={"task-02": "board-task-02"},
        artifact_dir=tmp_path,
    )
    return parent, envelope, broker, context


def _legacy_text_request(
    request_id: str,
    capability_id: str,
    *,
    extra_args: dict | None = None,
) -> dict:
    return {
        "output": (
            "I need observed evidence before final diagnosis.\n"
            + json.dumps({
                "tool": "br_harness_capability_request",
                "capability_id": capability_id,
                "args": {
                    "artifact_refs": [
                        "artifact:incident-evidence-packet.json"
                    ],
                    **dict(extra_args or {}),
                },
                "request_id": request_id,
            })
        ),
        "provider_attempts": [{"status": "EXECUTED"}],
    }


def _legacy_request(
    request_id: str,
    capability_id: str,
    *,
    extra_args: dict | None = None,
) -> dict:
    return {
        "output": json.dumps({
            "schema": "AgentTurnEnvelope/v1",
            "kind": "TOOL_REQUEST",
            "tool_request": {
                "schema": "ToolRequestEnvelope/v1",
                "request_id": request_id,
                "mission_id": "mission-semantic-tool-loop",
                "task_id": "task-02",
                "agent_id": "addy-agent-skills",
                "capability_id": "addy:debugging-and-error-recovery",
                "tool_or_capability_id": capability_id,
                "operation": "EXECUTE_CAPABILITY",
                "arguments": {
                    "artifact_refs": [
                        "artifact:incident-evidence-packet.json"
                    ],
                    **dict(extra_args or {}),
                },
                "input_refs": [
                    "artifact:incident-evidence-packet.json"
                ],
                "reason": "Read observed evidence with the authorized tool.",
                "authorization_context": {
                    "authority": "DEEPSEEK_HARNESS"
                },
            },
            "final_output": None,
        }),
        "provider_attempts": [{"status": "EXECUTED"}],
    }


def _near_final_diagnosis_without_schema() -> dict:
    return {
        "output": json.dumps({
            "schema": "AgentTurnEnvelope/v1",
            "kind": "FINAL_OUTPUT",
            "tool_request": None,
            "final_output": {
                "failure_class": "PLANNER_CONTRACT_REGISTRY_SELECTION_FAILURE",
                "observed_evidence": [
                    "artifact:incident-evidence-packet.json"
                ],
                "localization": "Registry selection for production-planning",
                "confidence": 0.96,
                "evidence_refs": [
                    "artifact:incident-evidence-packet.json"
                ],
            },
        }),
        "provider_attempts": [{"status": "EXECUTED"}],
    }


def _final_diagnosis() -> dict:
    return {
        "output": json.dumps({
            "schema": "AgentTurnEnvelope/v1",
            "kind": "FINAL_OUTPUT",
            "tool_request": None,
            "final_output": {
                "schema": "IncidentDiagnosisEvidence",
                "failure_class": "PLANNER_CONTRACT_REGISTRY_SELECTION_FAILURE",
                "observed_evidence": [
                    "artifact:incident-evidence-packet.json"
                ],
                "localization": "Registry selection for production-planning",
                "confidence": 0.96,
                "evidence_refs": [
                    "artifact:incident-evidence-packet.json"
                ],
            },
        }),
        "provider_attempts": [{"status": "EXECUTED"}],
    }


def test_legacy_structured_request_is_normalized_but_free_text_is_not():
    request = extract_tool_request(
        _legacy_text_request("diag-01", "artifact.evidence.reuse"),
        mission_id="mission-a",
        task_id="task-02",
        agent_id="addy-agent-skills",
        capability_id="addy:debugging-and-error-recovery",
    )
    assert request is not None
    assert request.schema == TOOL_REQUEST_SCHEMA
    assert request.source_format == "LEGACY_STRUCTURED_CAPABILITY_REQUEST"
    assert request.tool_or_capability_id == "artifact.evidence.reuse"
    assert request.input_refs == (
        "artifact:incident-evidence-packet.json",
    )

    assert extract_tool_request(
        {"output": "I will investigate this failure now."},
        mission_id="mission-a",
        task_id="task-02",
        agent_id="addy-agent-skills",
        capability_id="addy:debugging-and-error-recovery",
    ) is None


def test_tool_result_returns_to_same_agent_task_and_final_schema_completes(
    monkeypatch,
    tmp_path,
):
    parent, envelope, broker, context = _fixture(tmp_path)
    calls = []

    def fake_execute(**kwargs):
        task = kwargs["task_envelope"]
        calls.append({
            "capability_id": task.capability_id,
            "task_id": task.task_id,
            "payload": kwargs["payload"],
        })
        if task.capability_id == "artifact.evidence.reuse":
            assert kwargs["payload"]["input_artifact_refs"] == [
                "artifact:incident-evidence-packet.json"
            ]
            assert kwargs["payload"]["context"]["input_artifacts"]
            return SimpleNamespace(
                result={
                    "status": "REUSED",
                    "artifact_refs": [
                        "artifact:incident-evidence-packet.json"
                    ],
                    "evidence_summary": [{"observed": True}],
                },
                elapsed_seconds=0.001,
            )
        addy_calls = [
            item for item in calls
            if item["capability_id"]
            == "addy:debugging-and-error-recovery"
        ]
        if len(addy_calls) == 1:
            return SimpleNamespace(
                result=_legacy_request(
                    "diag-01",
                    "artifact.evidence.reuse",
                ),
                elapsed_seconds=0.001,
            )
        tool_results = kwargs["payload"]["context"]["agent_tool_results"]
        assert tool_results[0]["schema"] == "ToolResultEnvelope/v1"
        assert tool_results[0]["mission_id"] == envelope.mission_id
        assert tool_results[0]["task_id"] == "task-02"
        if len(addy_calls) == 2:
            return SimpleNamespace(
                result=_near_final_diagnosis_without_schema(),
                elapsed_seconds=0.001,
            )
        feedback = kwargs["payload"]["context"][
            "output_validation_feedback"
        ]
        assert feedback["expected_schema"] == "IncidentDiagnosisEvidence"
        assert feedback["errors"] == ["FINAL_STRUCTURED_OUTPUT_MISSING"]
        return SimpleNamespace(
            result=_final_diagnosis(),
            elapsed_seconds=0.001,
        )

    monkeypatch.setattr(broker.adapter, "execute", fake_execute)
    try:
        result = broker.execute_delegated_capability(
            task_id="task-02",
            capability_id="addy:debugging-and-error-recovery",
            payload={
                "mission_id": envelope.mission_id,
                "task_id": "task-02",
                "goal_id": envelope.goal_id,
                "task": "Diagnose the observed failure.",
                "context": context,
            },
            dependency_context=context,
        )
        assert result["executed"] is True
        assert result["agent_loop"]["agent_turns"] == 3
        assert result["agent_loop"]["tool_calls"] == 1
        assert result["agent_loop"]["provider_calls"] == 3
        assert result["agent_loop"]["final_output_valid"] is True
        assert [item["capability_id"] for item in calls] == [
            "addy:debugging-and-error-recovery",
            "artifact.evidence.reuse",
            "addy:debugging-and-error-recovery",
            "addy:debugging-and-error-recovery",
        ]
        assert (
            calls[0]["task_id"]
            == calls[2]["task_id"]
            == calls[3]["task_id"]
            == "task-02"
        )
        instance_ids = [
            calls[index]["payload"]["agent_instance_id"]
            for index in (0, 2, 3)
        ]
        assert len(set(instance_ids)) == 1
        for index in (0, 2, 3):
            projection = calls[index]["payload"]["context"][
                "agent_session"
            ]
            assert projection["agent_instance_id"] == instance_ids[0]
            assert projection["checkpoint_ref"].startswith(
                "artifact:agent-sessions/"
            )

        statuses = [
            row["status"]
            for row in broker.result_snapshot()["task-02"]
        ]
        assert "WAITING_TOOL" in statuses
        assert "OUTPUT_VALIDATION" in statuses
        assert statuses[-1] == "COMPLETED"
        tool_files = list((tmp_path / "tool-results").glob("*.json"))
        assert len(tool_files) == 1
        persisted = json.loads(tool_files[0].read_text())
        assert persisted["schema"] == "ToolResultEnvelope/v1"
        assert persisted["status"] == "EXECUTED"
        assert any(
            item["event"] == "TASK_WAITING_TOOL"
            for item in broker.audit_snapshot()
        )
        assert any(
            item["event"] == "TOOL_EXECUTED"
            for item in broker.audit_snapshot()
        )
        completed_task_result = json.loads(
            (tmp_path / "task-results" / "task-02-3.json").read_text()
        )
        assert "artifact:incident-evidence-packet.json" in (
            completed_task_result["evidence_refs"]
        )
        session_files = list(
            (tmp_path / "agent-sessions").glob("task-02-agent-*.json")
        )
        assert len(session_files) == 1
        session = json.loads(session_files[0].read_text())
        assert session["schema"] == "AgentSession/v1"
        assert session["AGENT_INSTANCE_ID"] == instance_ids[0]
        assert session["STATUS"] == "COMPLETED"
        assert session["TURN_INDEX"] == 3
        assert session["FINAL_OUTPUT_SCHEMA"] == (
            "IncidentDiagnosisEvidence"
        )
        assert session["FINAL_OUTPUT_VALID"] is True
        assert len(session["TOOL_REQUESTS"]) == 1
        assert len(session["TOOL_EXECUTIONS"]) == 1
        assert len(session["TOOL_RESULTS_CONSUMED"]) == 1
    finally:
        consume_harness_authorization(parent)


def test_mutating_tool_request_from_diagnosis_fails_closed(
    monkeypatch,
    tmp_path,
):
    parent, envelope, broker, context = _fixture(tmp_path)
    calls = []

    def fake_execute(**kwargs):
        calls.append(kwargs["task_envelope"].capability_id)
        return SimpleNamespace(
            result=_legacy_request(
                "diag-mutate",
                "agent-office.codex.bounded-development",
            ),
            elapsed_seconds=0.001,
        )

    monkeypatch.setattr(broker.adapter, "execute", fake_execute)
    try:
        with pytest.raises(DelegatedCapabilityFailure) as raised:
            broker.execute_delegated_capability(
                task_id="task-02",
                capability_id="addy:debugging-and-error-recovery",
                payload={
                    "mission_id": envelope.mission_id,
                    "task_id": "task-02",
                    "goal_id": envelope.goal_id,
                    "task": "Diagnose only.",
                    "context": context,
                },
                dependency_context=context,
            )
        assert raised.value.failure_mode == "AgentToolAuthorizationError"
        assert calls == ["addy:debugging-and-error-recovery"]
        statuses = [
            row["status"]
            for row in broker.result_snapshot()["task-02"]
        ]
        assert statuses == ["WAITING_TOOL", "FAILED_TOOL"]
        assert not any(
            row["event"] == "TASK_COMPLETED"
            for row in broker.audit_snapshot()
        )
    finally:
        consume_harness_authorization(parent)


def test_tool_loop_exceeding_budget_fails_budget(
    monkeypatch,
    tmp_path,
):
    parent, envelope, broker, context = _fixture(
        tmp_path,
        tool_budget=1,
    )
    addy_turn = {"count": 0}

    def fake_execute(**kwargs):
        task = kwargs["task_envelope"]
        if task.capability_id == "artifact.evidence.reuse":
            return SimpleNamespace(
                result={"status": "REUSED", "evidence_summary": []},
                elapsed_seconds=0.001,
            )
        addy_turn["count"] += 1
        return SimpleNamespace(
            result=_legacy_request(
                f"diag-{addy_turn['count']}",
                "artifact.evidence.reuse",
                extra_args={"probe_variant": addy_turn["count"]},
            ),
            elapsed_seconds=0.001,
        )

    monkeypatch.setattr(broker.adapter, "execute", fake_execute)
    try:
        with pytest.raises(DelegatedCapabilityFailure) as raised:
            broker.execute_delegated_capability(
                task_id="task-02",
                capability_id="addy:debugging-and-error-recovery",
                payload={
                    "mission_id": envelope.mission_id,
                    "task_id": "task-02",
                    "goal_id": envelope.goal_id,
                    "task": "Diagnose with bounded tool use.",
                    "context": context,
                },
                dependency_context=context,
            )
        assert raised.value.failure_mode == "AgentToolBudgetExceeded"
        statuses = [
            row["status"]
            for row in broker.result_snapshot()["task-02"]
        ]
        assert statuses[-1] == "FAILED_BUDGET"
        assert not any(
            row["event"] == "TASK_COMPLETED"
            for row in broker.audit_snapshot()
        )
    finally:
        consume_harness_authorization(parent)


def test_preliminary_prose_still_fails_contract_without_completion(
    monkeypatch,
    tmp_path,
):
    parent, envelope, broker, context = _fixture(tmp_path)

    def fake_execute(**_kwargs):
        return SimpleNamespace(
            result={
                "output": "I will investigate.",
                "provider_attempts": [{"status": "EXECUTED"}],
            },
            elapsed_seconds=0.001,
        )

    monkeypatch.setattr(broker.adapter, "execute", fake_execute)
    try:
        with pytest.raises(DelegatedCapabilityFailure) as raised:
            broker.execute_delegated_capability(
                task_id="task-02",
                capability_id="addy:debugging-and-error-recovery",
                payload={
                    "mission_id": envelope.mission_id,
                    "task_id": "task-02",
                    "goal_id": envelope.goal_id,
                    "task": "Diagnose the failure.",
                    "context": context,
                },
                dependency_context=context,
            )
        assert raised.value.failure_mode == "AgentTurnContractError"
        statuses = [
            row["status"]
            for row in broker.result_snapshot()["task-02"]
        ]
        assert statuses[-1] == "FAILED_CONTRACT"
        assert not any(
            row["event"] == "TASK_COMPLETED"
            for row in broker.audit_snapshot()
        )
    finally:
        consume_harness_authorization(parent)


def test_semantically_duplicate_tool_request_reuses_prior_result_without_execution(
    monkeypatch,
    tmp_path,
):
    parent, envelope, broker, context = _fixture(tmp_path)
    calls = []
    addy_turn = {"count": 0}

    def fake_execute(**kwargs):
        task = kwargs["task_envelope"]
        calls.append(task.capability_id)
        if task.capability_id == "artifact.evidence.reuse":
            return SimpleNamespace(
                result={
                    "status": "REUSED",
                    "artifact_refs": [
                        "artifact:incident-evidence-packet.json"
                    ],
                    "evidence_summary": [{"bounded": True}],
                },
                elapsed_seconds=0.001,
            )
        addy_turn["count"] += 1
        if addy_turn["count"] == 1:
            result = _legacy_request(
                "diag-dup-1",
                "artifact.evidence.reuse",
            )
        elif addy_turn["count"] == 2:
            result = _legacy_request(
                "diag-dup-2",
                "artifact.evidence.reuse",
            )
        else:
            result = _final_diagnosis()
        return SimpleNamespace(result=result, elapsed_seconds=0.001)

    monkeypatch.setattr(broker.adapter, "execute", fake_execute)
    try:
        result = broker.execute_delegated_capability(
            task_id="task-02",
            capability_id="addy:debugging-and-error-recovery",
            payload={
                "mission_id": envelope.mission_id,
                "task_id": "task-02",
                "goal_id": envelope.goal_id,
                "task": "Diagnose with no duplicate tool execution.",
                "context": context,
            },
            dependency_context=context,
        )
        assert result["executed"] is True
        assert result["agent_loop"]["agent_turns"] == 3
        assert result["agent_loop"]["tool_calls"] == 1
        assert result["agent_loop"]["tool_request_count"] == 2
        assert calls == [
            "addy:debugging-and-error-recovery",
            "artifact.evidence.reuse",
            "addy:debugging-and-error-recovery",
            "addy:debugging-and-error-recovery",
        ]
        assert any(
            row["event"] == "TOOL_RESULT_REUSED"
            and row["DUPLICATE_TOOL_EXECUTION_AVOIDED"] == "PASS"
            for row in broker.audit_snapshot()
        )
        persisted = json.loads(
            (
                tmp_path
                / "tool-results"
                / "task-02-diag-dup-2.json"
            ).read_text()
        )
        assert persisted["status"] == "REUSED"
        assert persisted["result_payload"][
            "duplicate_tool_execution_avoided"
        ] is True
    finally:
        consume_harness_authorization(parent)


def test_deterministic_system_improvement_proposal_does_not_claim_semantic_reasoning():
    record = GLOBAL_CAPABILITY_REGISTRY.get("system.improvement.propose")
    assert record is not None
    assert record.provider_id == "internal"
    assert record.latency_class == "LOCAL"
    assert CAN_SEMANTIC_REASONING not in set(
        record.execution_operations or ()
    )


def test_agent_turn_rejects_nested_reason_without_tool_execution(
    monkeypatch,
    tmp_path,
):
    parent, envelope, broker, context = _fixture(tmp_path)
    calls = []

    def fake_execute(**kwargs):
        task = kwargs["task_envelope"]
        calls.append(task.capability_id)
        return SimpleNamespace(
            result={
                "output": json.dumps({
                    "schema": "AgentTurnEnvelope/v1",
                    "kind": "TOOL_REQUEST",
                    "tool_request": {
                        "schema": "ToolRequestEnvelope/v1",
                        "request_id": "nested-reason",
                        "mission_id": envelope.mission_id,
                        "task_id": "task-02",
                        "agent_id": "addy-agent-skills",
                        "capability_id": "addy:debugging-and-error-recovery",
                        "tool_or_capability_id": "artifact.evidence.reuse",
                        "operation": "EXECUTE_CAPABILITY",
                        "arguments": {
                            "reason": "invalid nested reason",
                            "artifact_refs": [
                                "artifact:incident-evidence-packet.json"
                            ],
                        },
                        "input_refs": [
                            "artifact:incident-evidence-packet.json"
                        ],
                        "authorization_context": {
                            "authority": "DEEPSEEK_HARNESS"
                        },
                    },
                    "final_output": None,
                }),
                "provider_attempts": [{"status": "EXECUTED"}],
            },
            elapsed_seconds=0.001,
        )

    monkeypatch.setattr(broker.adapter, "execute", fake_execute)
    try:
        with pytest.raises(DelegatedCapabilityFailure) as raised:
            broker.execute_delegated_capability(
                task_id="task-02",
                capability_id="addy:debugging-and-error-recovery",
                payload={
                    "mission_id": envelope.mission_id,
                    "task_id": "task-02",
                    "goal_id": envelope.goal_id,
                    "task": "Diagnose strictly.",
                    "context": context,
                },
                dependency_context=context,
            )
        assert raised.value.failure_mode == "AgentToolRequestError"
        assert calls == ["addy:debugging-and-error-recovery"]
        statuses = [
            row["status"]
            for row in broker.result_snapshot()["task-02"]
        ]
        assert statuses == ["FAILED_CONTRACT"]
        assert not any(
            row["event"] == "TOOL_EXECUTED"
            for row in broker.audit_snapshot()
        )
    finally:
        consume_harness_authorization(parent)


def test_agent_turn_rejects_fake_tool_result_mixed_response(
    monkeypatch,
    tmp_path,
):
    parent, envelope, broker, context = _fixture(tmp_path)
    calls = []

    valid_turn = json.dumps({
        "schema": "AgentTurnEnvelope/v1",
        "kind": "TOOL_REQUEST",
        "tool_request": {
            "schema": "ToolRequestEnvelope/v1",
            "request_id": "fake-tool-result",
            "mission_id": envelope.mission_id,
            "task_id": "task-02",
            "agent_id": "addy-agent-skills",
            "capability_id": "addy:debugging-and-error-recovery",
            "tool_or_capability_id": "artifact.evidence.reuse",
            "operation": "EXECUTE_CAPABILITY",
            "arguments": {
                "artifact_refs": [
                    "artifact:incident-evidence-packet.json"
                ]
            },
            "input_refs": [
                "artifact:incident-evidence-packet.json"
            ],
            "reason": "Read observed evidence.",
            "authorization_context": {
                "authority": "DEEPSEEK_HARNESS"
            },
        },
        "final_output": None,
    })

    def fake_execute(**kwargs):
        calls.append(kwargs["task_envelope"].capability_id)
        return SimpleNamespace(
            result={
                "output": (
                    valid_turn
                    + '\n<tool_result>{"schema":"ToolResultEnvelope/v1"}</tool_result>'
                ),
                "provider_attempts": [{"status": "EXECUTED"}],
            },
            elapsed_seconds=0.001,
        )

    monkeypatch.setattr(broker.adapter, "execute", fake_execute)
    try:
        with pytest.raises(DelegatedCapabilityFailure) as raised:
            broker.execute_delegated_capability(
                task_id="task-02",
                capability_id="addy:debugging-and-error-recovery",
                payload={
                    "mission_id": envelope.mission_id,
                    "task_id": "task-02",
                    "goal_id": envelope.goal_id,
                    "task": "Diagnose strictly.",
                    "context": context,
                },
                dependency_context=context,
            )
        assert raised.value.failure_mode == "AgentTurnContractError"
        assert calls == ["addy:debugging-and-error-recovery"]
        assert not any(
            row["event"] == "TOOL_EXECUTED"
            for row in broker.audit_snapshot()
        )
        failure = broker.result_snapshot()["task-02"][-1]
        assert failure["status"] == "FAILED_CONTRACT"
        assert failure["result"]["FAKE_TOOL_RESULT_ACCEPTED"] == "NO"
    finally:
        consume_harness_authorization(parent)



def test_restored_session_resumes_after_real_tool_result_without_reexecution(
    monkeypatch,
    tmp_path,
):
    parent, envelope, broker, context = _fixture(tmp_path)
    record = GLOBAL_CAPABILITY_REGISTRY.get(
        "addy:debugging-and-error-recovery"
    )
    assert record is not None
    session = AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id=envelope.mission_id,
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy-agent-skills",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=(
            "artifact:incident-evidence-packet.json",
        ),
        max_agent_turns=4,
        max_tool_calls=2,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=120,
    )
    session.begin_turn(1)
    request = extract_tool_request(
        _legacy_request(
            "diag-restored-1",
            "artifact.evidence.reuse",
        ),
        mission_id=envelope.mission_id,
        task_id="task-02",
        agent_id="addy-agent-skills",
        capability_id="addy:debugging-and-error-recovery",
    )
    assert request is not None
    session.record_tool_request(request.to_dict())
    started = utcnow()
    result_envelope = build_tool_result_envelope(
        request=request,
        tool_id="artifact.evidence.reuse",
        operation="EXECUTE_CAPABILITY",
        authorization_id="tool-auth-restored",
        output_refs=(
            "artifact:tool-results/task-02-diag-restored-1.json",
        ),
        result_payload={
            "status": "REUSED",
            "artifact_refs": [
                "artifact:incident-evidence-packet.json"
            ],
            "evidence_summary": [{"observed": True}],
        },
        status="EXECUTED",
        started_at=started,
        finished_at=utcnow(),
        error=None,
    ).to_dict()
    tool_path = (
        tmp_path
        / "tool-results"
        / "task-02-diag-restored-1.json"
    )
    tool_path.parent.mkdir(parents=True, exist_ok=True)
    tool_path.write_text(
        json.dumps(result_envelope),
        encoding="utf-8",
    )
    session.record_tool_result(result_envelope)
    session.begin_turn(2)
    session.fail(
        failure_class="CapabilityReturnedFailure",
        evidence={
            "result": {
                "FAILURE_CLASS": "TRANSIENT_PROVIDER_TIMEOUT",
                "ATTEMPTED_PROVIDER_MODEL_PAIRS": [
                    {
                        "provider_id": "nvidia_nim",
                        "model_id": "z-ai/glm-5.3",
                        "routing_id": "route-old-a",
                        "attempt_id": "attempt-a",
                        "failure_class": "TRANSIENT_PROVIDER_HTTP_5XX",
                        "status": "FAILED",
                    },
                    {
                        "provider_id": "nvidia_nim",
                        "model_id": (
                            "nvidia/nemotron-3.5-lightning-30b-a3b"
                        ),
                        "routing_id": "route-old-b",
                        "attempt_id": "attempt-b",
                        "failure_class": "TRANSIENT_PROVIDER_TIMEOUT",
                        "status": "FAILED",
                    },
                ],
                "EXHAUSTED_PROVIDER_MODEL_PAIRS": [
                    {
                        "provider_id": "nvidia_nim",
                        "model_id": "z-ai/glm-5.3",
                        "routing_id": "route-old-a",
                        "attempt_id": "attempt-a",
                        "failure_class": "TRANSIENT_PROVIDER_HTTP_5XX",
                        "status": "FAILED",
                    },
                    {
                        "provider_id": "nvidia_nim",
                        "model_id": (
                            "nvidia/nemotron-3.5-lightning-30b-a3b"
                        ),
                        "routing_id": "route-old-b",
                        "attempt_id": "attempt-b",
                        "failure_class": "TRANSIENT_PROVIDER_TIMEOUT",
                        "status": "FAILED",
                    },
                ],
                "provider_attempts": [
                    {
                        "provider_id": "nvidia_nim",
                        "model_id": "z-ai/glm-5.3",
                        "routing_id": "route-old-a",
                        "attempt_id": "attempt-a",
                        "failure_class": "TRANSIENT_PROVIDER_HTTP_5XX",
                        "status": "FAILED",
                    },
                    {
                        "provider_id": "nvidia_nim",
                        "model_id": (
                            "nvidia/nemotron-3.5-lightning-30b-a3b"
                        ),
                        "routing_id": "route-old-b",
                        "attempt_id": "attempt-b",
                        "failure_class": "TRANSIENT_PROVIDER_TIMEOUT",
                        "status": "FAILED",
                    },
                ],
            }
        },
    )

    calls = []

    def fake_execute(**kwargs):
        task = kwargs["task_envelope"]
        calls.append(task.capability_id)
        assert task.capability_id == (
            "addy:debugging-and-error-recovery"
        )
        payload = kwargs["payload"]
        assert payload["agent_turn"] == 3
        assert payload["agent_instance_id"] == session.agent_instance_id
        assert len(
            payload["context"]["agent_tool_results"]
        ) == 1
        internal = payload["context"]["internal_recovery"]
        assert internal["RECOVERY_STRATEGY"] == (
            "LOCALIZED_PROVIDER_REPLAN"
        )
        assert len(
            internal["EXHAUSTED_PROVIDER_MODEL_PAIRS"]
        ) == 2
        assert internal["SAME_MODEL_FULL_TIMEOUT_RETRY"] == "FORBIDDEN"
        return SimpleNamespace(
            result=_final_diagnosis(),
            elapsed_seconds=0.001,
        )

    monkeypatch.setattr(broker.adapter, "execute", fake_execute)
    try:
        result = broker.execute_delegated_capability(
            task_id="task-02",
            capability_id="addy:debugging-and-error-recovery",
            payload={
                "mission_id": envelope.mission_id,
                "task_id": "task-02",
                "goal_id": envelope.goal_id,
                "task": "Resume diagnosis from checkpoint.",
                "context": context,
            },
            dependency_context=context,
        )
        assert calls == ["addy:debugging-and-error-recovery"]
        assert result["agent_instance_id"] == session.agent_instance_id
        assert result["agent_loop"]["agent_turns"] == 3
        assert result["agent_loop"]["tool_calls"] == 1
        assert result["agent_loop"]["final_output_valid"] is True
        restored = [
            row for row in broker.audit_snapshot()
            if row["event"] == "AGENT_SESSION_RESTORED"
        ]
        assert len(restored) == 1
        assert restored[0]["restored_turn_index"] == 2
        assert restored[0]["restored_tool_result_count"] == 1
        assert restored[0]["TASK_AGENT_SESSION_RESTORED"] == "PASS"
        final_session = json.loads(session.path.read_text())
        assert final_session["TURN_INDEX"] == 3
        assert final_session["STATUS"] == "COMPLETED"
        assert len(final_session["TOOL_EXECUTIONS"]) == 1
        assert len(final_session["TOOL_RESULTS_CONSUMED"]) == 1
    finally:
        consume_harness_authorization(parent)



def test_resume_budget_extends_session_without_resetting_turn_history(
    tmp_path,
):
    session = AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-resume-budget",
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy-agent-skills",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=2,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=120,
    )
    for turn in range(1, 5):
        session.begin_turn(turn)
    session.fail(failure_class="PROVIDER_TRANSIENT")

    restored = AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-resume-budget",
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy-agent-skills",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=2,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=120,
    )
    first = restored.reserve_turn_window(
        default_max_agent_turns=4,
        max_resume_agent_turns=2,
        max_resume_segments=2,
        max_total_agent_turns=8,
    )
    assert first["start_turn"] == 5
    assert first["end_turn"] == 6
    assert first["historical_turns"] == 4
    assert first["AGENT_RESUME_BUDGET_BOUNDED"] is True
    assert first["AGENT_RESUME_BUDGET_NOT_RESET_BLINDLY"] is True
    restored.begin_turn(6)
    restored.fail(failure_class="PROVIDER_TRANSIENT")

    again = AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-resume-budget",
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy-agent-skills",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=2,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=120,
    )
    second = again.reserve_turn_window(
        default_max_agent_turns=4,
        max_resume_agent_turns=2,
        max_resume_segments=2,
        max_total_agent_turns=8,
    )
    assert second["start_turn"] == 7
    assert second["end_turn"] == 8
    again.begin_turn(8)
    again.fail(failure_class="PROVIDER_TRANSIENT")

    exhausted = AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-resume-budget",
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy-agent-skills",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=2,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=120,
    )
    third = exhausted.reserve_turn_window(
        default_max_agent_turns=4,
        max_resume_agent_turns=2,
        max_resume_segments=2,
        max_total_agent_turns=8,
    )
    assert third["exhausted"] is True
    assert exhausted.state["TURN_INDEX"] == 8
    assert exhausted.state["MAX_AGENT_TURNS"] == 4



def test_resume_segments_do_not_hide_remaining_absolute_turn_budget(
    tmp_path,
):
    session = AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-resume-segment-budget",
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy-agent-skills",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=2,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=120,
    )
    session.state["TURN_INDEX"] = 6
    session.state["RESUME_SEGMENTS_USED"] = 2
    session._persist()

    restored = AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-resume-segment-budget",
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy-agent-skills",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=2,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=120,
    )
    window = restored.reserve_turn_window(
        default_max_agent_turns=4,
        max_resume_agent_turns=2,
        max_resume_segments=4,
        max_total_agent_turns=8,
    )
    assert window["exhausted"] is False
    assert window["resume_segment"] == 3
    assert window["historical_turns"] == 6
    assert window["start_turn"] == 7
    assert window["end_turn"] == 8
    assert restored.state["MAX_AGENT_TURNS"] == 4
    assert restored.state["MAX_TOTAL_AGENT_TURNS"] == 8



def test_legacy_pre_provider_routing_failure_reclaims_phantom_turn_once(
    tmp_path,
):
    session = AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-phantom-turn",
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy-agent-skills",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=2,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=120,
    )
    session.state["TURN_INDEX"] = 8
    session.state["RESUME_SEGMENTS_USED"] = 4
    session.state["STATUS"] = "FAILED"
    session.state["FAILURE_CLASS"] = "RoutingPolicyError"
    session.state.pop("FAILURE_TURN_CONSUMED", None)
    session._persist()

    restored = AgentSessionRuntime(
        artifact_dir=tmp_path,
        mission_id="mission-phantom-turn",
        task_id="task-02",
        capability_id="addy:debugging-and-error-recovery",
        agent_id="addy-agent-skills",
        skill_id="debugging-and-error-recovery",
        functional_role="DIAGNOSIS",
        execution_kind="SEMANTIC_REASONER",
        allowed_tools=("artifact.evidence.reuse",),
        input_artifact_refs=("artifact:incident.json",),
        max_agent_turns=4,
        max_tool_calls=2,
        max_provider_calls=8,
        max_context_chars=15000,
        max_wall_clock_seconds=120,
    )
    assert restored.reclaim_unexecuted_pre_provider_turn() is True
    assert restored.state["TURN_INDEX"] == 7
    assert restored.state["RESUME_SEGMENTS_USED"] == 3
    assert restored.state["FAILURE_TURN_CONSUMED"] is False
    assert restored.reclaim_unexecuted_pre_provider_turn() is False


def test_pre_provider_routing_failure_does_not_consume_agent_turn(
    monkeypatch,
    tmp_path,
):
    parent, envelope, broker, context = _fixture(tmp_path)

    def fail_before_provider(**kwargs):
        raise RoutingPolicyError(
            "Primary provider is unavailable and fallback is not permitted",
            evidence={
                "primary_provider": "nvidia_nim",
                "fallback_allowed": False,
            },
        )

    monkeypatch.setattr(broker.adapter, "execute", fail_before_provider)
    try:
        with pytest.raises(DelegatedCapabilityFailure) as raised:
            broker.execute_delegated_capability(
                task_id="task-02",
                capability_id="addy:debugging-and-error-recovery",
                payload={
                    "mission_id": envelope.mission_id,
                    "task_id": "task-02",
                    "goal_id": envelope.goal_id,
                    "task": "Resume diagnosis without a provider yet.",
                    "context": context,
                },
                dependency_context=context,
            )
        assert raised.value.failure_mode == "RoutingPolicyError"
        session_files = list(
            (tmp_path / "agent-sessions").glob("task-02-agent-*.json")
        )
        assert len(session_files) == 1
        state = json.loads(session_files[0].read_text(encoding="utf-8"))
        assert state["TURN_INDEX"] == 0
        assert state["FAILURE_CLASS"] == "RoutingPolicyError"
        assert state["FAILURE_TURN_CONSUMED"] is False
    finally:
        consume_harness_authorization(parent)
