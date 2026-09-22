from __future__ import annotations

from pathlib import Path

from app.services.harness_collaboration_service import TaskEnvelope
from scripts.dynamic_system_improvement_mission import (
    _generic_payload,
    _is_mutating,
)


def _task(*, mutating: bool) -> TaskEnvelope:
    return TaskEnvelope.from_mapping({
        "task_id": "dynamic-task",
        "capability_id": (
            "agent-office.codex.bounded-development"
            if mutating
            else "agent-office.codex.readonly-analysis"
        ),
        "authorized_action": "DEVELOPMENT",
        "objective": (
            "Create a bounded candidate"
            if mutating
            else "Analyze the bounded system problem"
        ),
        "task_class": (
            "bounded-development" if mutating else "readonly-analysis"
        ),
        "required_capability_description": (
            "bounded code mutation" if mutating else "read-only root cause analysis"
        ),
        "dependencies": [],
        "input_refs": ["artifact:input"],
        "expected_output": "StructuredEngineeringEvidence",
        "acceptance_criteria": ["stay within TaskEnvelope"],
        "read_scope": ["app", "tests"],
        "write_scope": ["app"] if mutating else [],
        "allowed_tools": ["git", "python", "pytest", "codex", "rg", "cat"],
        "allowed_side_effects": (
            ["ephemeral worktree", "local candidate commit"]
            if mutating else ["ephemeral worktree"]
        ),
        "forbidden_side_effects": ["push", "merge", "publication"],
        "time_budget_seconds": 300,
        "cost_budget": 0.0,
        "context_budget_bytes": 16384,
        "tool_budget": 12,
        "retry_budget": 1,
        "evidence_contract": "StructuredEngineeringEvidence",
        "review_policy": "INDEPENDENT_REQUIRED" if mutating else "NONE",
        "risk_side_effect_class": (
            "BOUNDED_MUTATION" if mutating else "READ_ONLY"
        ),
        "human_gate_policy": "NONE",
    })


def _payload(task: TaskEnvelope):
    return _generic_payload(
        task=task,
        human_goal="Improve a measured system inefficiency safely.",
        goal_id="goal-generic-scope",
        mission_id="mission-generic-scope",
        base_sha="a" * 40,
        branch="work/gate6f-analytics-learning",
        snapshot={"signal": "bounded"},
        parent_context={
            "evidence_refs": ["artifact:parent-evidence"],
        },
    )


def test_generic_dynamic_payload_uses_task_envelope_scope_only():
    task = _task(mutating=True)
    payload = _payload(task)
    assert payload["task_id"] == task.task_id
    assert payload["mission_read_scope"] == ["app", "tests"]
    assert payload["mission_write_scope"] == ["app"]
    assert payload["read_set"] == ["app", "tests"]
    assert payload["write_set"] == ["app"]
    assert payload["allowed_paths"] == ["app"]
    assert set(payload["allowed_actions"]) >= {
        "analyze", "inspect", "test", "benchmark", "edit", "commit_candidate"
    }
    assert payload["gaps"] == ["bounded code mutation"]
    assert "artifact:parent-evidence" in payload["evidence_refs"]
    assert _is_mutating(task) is True


def test_generic_dynamic_readonly_task_has_no_write_scope():
    task = _task(mutating=False)
    payload = _payload(task)
    assert payload["mission_write_scope"] == []
    assert payload["write_set"] == []
    assert payload["allowed_paths"] == []
    assert "edit" not in payload["allowed_actions"]
    assert "commit_candidate" not in payload["allowed_actions"]
    assert _is_mutating(task) is False


def test_dynamic_executor_contains_no_task_or_legacy_roster_hardcode():
    source = Path(
        "scripts/dynamic_system_improvement_mission.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "SPECIALISTS",
        "ROOT_CAUSE_READ_SCOPE",
        "CANDIDATE_READ_SCOPE",
        "VALIDATE_READ_SCOPE",
        "WRITE_SET",
        'if task_id == "measure"',
        'if task_id == "root-cause"',
        'if task_id == "candidate"',
        'if task_id == "validate"',
        '"legacy_fixed_specialists"',
        '"legacy_avoidable_agent_calls"',
    )
    for marker in forbidden:
        assert marker not in source
