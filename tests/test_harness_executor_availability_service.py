from types import SimpleNamespace

from app.services import harness_executor_availability_service as service


def _health(capability_id: str):
    state = (
        "BLOCKED"
        if capability_id.startswith("agent-office.codex.")
        else "HEALTHY"
    )
    return SimpleNamespace(state=state)


def _checkpoint_plan():
    return {
        "authority": "DEEPSEEK_HARNESS",
        "mission_id": "mission-3043b06fb2ec006c1f41",
        "plan_id": "plan-3043b06fb2ec006c1f41",
        "collaboration_plan": {
            "tasks": [
                {
                    "task_id": "instrument-planner",
                    "capability_id": "agent-office.codex.bounded-development",
                    "action": "DEVELOPMENT",
                    "objective": (
                        "Profile semantic planner execution to locate redundant "
                        "context, duplicate calls, and serial bottlenecks"
                    ),
                    "task_class": "DEVELOPMENT",
                    "expected_output": "profiling-report",
                    "dependencies": [],
                    "required_operations": [
                        "CAN_PRODUCE_ARTIFACT_REFS",
                        "CAN_READ_REPOSITORY",
                    ],
                    "candidate_requirement": "REQUIRED",
                    "risk_side_effect_class": "MEDIUM",
                },
                {
                    "task_id": "create-candidate",
                    "capability_id": "agent-office.codex.bounded-development",
                    "action": "DEVELOPMENT",
                    "objective": (
                        "Implement minimal isolated candidate addressing the "
                        "identified bottleneck"
                    ),
                    "task_class": "DEVELOPMENT",
                    "expected_output": "candidate-patch",
                    "dependencies": ["instrument-planner"],
                    "required_operations": [
                        "CAN_CONSUME_ARTIFACT_REFS",
                        "CAN_PRODUCE_ARTIFACT_REFS",
                        "CAN_SEMANTIC_REASONING",
                    ],
                    "candidate_requirement": "CONDITIONAL",
                    "risk_side_effect_class": "MEDIUM",
                },
                {
                    "task_id": "validate-candidate",
                    "capability_id": "agent-office.codex.bounded-development",
                    "action": "DEVELOPMENT",
                    "objective": (
                        "Benchmark candidate vs 14105.371 ms baseline and verify "
                        "no quality, safety, evidence, or authorization regression"
                    ),
                    "task_class": "DEVELOPMENT",
                    "expected_output": "validation-report",
                    "dependencies": ["create-candidate"],
                    "required_operations": [
                        "CAN_CONSUME_ARTIFACT_REFS",
                        "CAN_PRODUCE_ARTIFACT_REFS",
                        "CAN_READ_REPOSITORY",
                        "CAN_RUN_BENCHMARK",
                    ],
                    "candidate_requirement": "CONDITIONAL",
                    "risk_side_effect_class": "MEDIUM",
                },
            ]
        },
    }


def test_checkpoint_resolves_no_complete_codex_alternative_without_provider(monkeypatch):
    monkeypatch.setattr(service, "capability_health", _health)
    result = service.resolve_blocked_executor_alternatives(
        _checkpoint_plan(),
        blocked_capability_ids={"agent-office.codex.bounded-development"},
    )

    assert result["ALTERNATIVE_EXECUTOR_RESOLUTION_DETERMINISTIC"] == "PASS"
    assert result["ALTERNATIVE_EXECUTOR_AVAILABLE"] == "NO"
    assert result["NO_ALTERNATIVE_EXECUTOR_REPLAN"] == "NO"
    assert result["PROVIDER_CALL_EXECUTED"] == "NO"
    assert result["SEMANTIC_REPLAN_PERFORMED"] == "NO"
    assert result["MISSION_STATE"] == "WAITING_FOR_EXTERNAL_AUTH"

    by_task = {item["task_id"]: item for item in result["blocked_tasks"]}
    assert any(
        item["capability_id"] == "agent-office.deterministic-analysis"
        for item in by_task["instrument-planner"]["alternatives"]
    )
    assert "CAN_MUTATE_CANDIDATE" in by_task["create-candidate"][
        "required_operations"
    ]
    assert "CAN_WRITE_REPOSITORY" in by_task["create-candidate"][
        "required_operations"
    ]
    assert "CAN_RUN_TESTS" in by_task["create-candidate"][
        "required_operations"
    ]
    assert by_task["create-candidate"]["alternatives"] == []


def test_read_only_blocked_executor_can_be_replaced_deterministically(monkeypatch):
    monkeypatch.setattr(service, "capability_health", _health)
    plan = {
        "authority": "DEEPSEEK_HARNESS",
        "mission_id": "mission-readonly",
        "plan_id": "plan-readonly",
        "collaboration_plan": {
            "tasks": [
                {
                    "task_id": "profile",
                    "capability_id": "agent-office.codex.readonly-analysis",
                    "action": "DEVELOPMENT",
                    "objective": "Profile repository latency with evidence",
                    "task_class": "root-cause-analysis",
                    "expected_output": "profiling-report",
                    "dependencies": [],
                    "required_operations": [
                        "CAN_READ_REPOSITORY",
                        "CAN_PRODUCE_ARTIFACT_REFS",
                    ],
                    "candidate_requirement": "NOT_APPLICABLE",
                    "risk_side_effect_class": "READ_ONLY",
                }
            ]
        },
    }

    result = service.resolve_blocked_executor_alternatives(
        plan,
        blocked_capability_ids={"agent-office.codex.readonly-analysis"},
    )

    assert result["ALTERNATIVE_EXECUTOR_AVAILABLE"] == "YES"
    assert result["MISSION_STATE"] == "ALTERNATIVE_EXECUTOR_DISCOVERED"
    alternatives = result["blocked_tasks"][0]["alternatives"]
    assert any(
        item["capability_id"] == "agent-office.deterministic-analysis"
        for item in alternatives
    )
    selected = next(
        item
        for item in alternatives
        if item["capability_id"] == "agent-office.deterministic-analysis"
    )
    assert selected["execution_contract_compatible"] is True
    assert selected["authority_compatible"] is True
    assert selected["side_effect_class_compatible"] is True
