from __future__ import annotations

from scripts.dynamic_system_improvement_mission import (
    CANDIDATE_READ_SCOPE,
    ROOT_CAUSE_READ_SCOPE,
    VALIDATE_READ_SCOPE,
    WRITE_SET,
    _payload,
)


def _base(task_id: str):
    return _payload(
        task_id=task_id,
        capability_id="agent-office.codex.bounded-development",
        human_goal="Improve the measured inefficiency without reducing quality.",
        goal_id="goal-scope-test",
        mission_id="mission-scope-test",
        base_sha="a" * 40,
        branch="work/gate6f-analytics-learning",
        snapshot={"dynamic_selected_task_count": 4},
        candidate_sha="b" * 40 if task_id == "validate" else None,
        parent_context={},
    )


def test_dynamic_candidate_scope_is_least_privilege_and_consistent():
    payload = _base("candidate")
    assert tuple(payload["mission_read_scope"]) == CANDIDATE_READ_SCOPE
    assert tuple(payload["mission_write_scope"]) == WRITE_SET
    assert tuple(payload["read_set"]) == CANDIDATE_READ_SCOPE
    assert tuple(payload["write_set"]) == WRITE_SET
    assert set(payload["write_set"]) <= set(payload["mission_write_scope"])
    assert set(payload["read_set"]) <= set(payload["mission_read_scope"])
    assert "app/services/harness_collaboration_service.py" in payload["mission_read_scope"]
    assert "app/services/harness_collaboration_service.py" not in payload["mission_write_scope"]


def test_readonly_specialists_get_no_write_scope():
    root_cause = _base("root-cause")
    validate = _base("validate")
    assert tuple(root_cause["mission_read_scope"]) == ROOT_CAUSE_READ_SCOPE
    assert root_cause["mission_write_scope"] == []
    assert tuple(validate["mission_read_scope"]) == VALIDATE_READ_SCOPE
    assert validate["mission_write_scope"] == []
