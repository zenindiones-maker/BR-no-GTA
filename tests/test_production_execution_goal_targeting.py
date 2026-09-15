import pytest

from app.database.gta6_goal_repository import get_gta6_goal
from app.services.gta6_goal_service import create_goal, set_goal_status
from app.services.harness_authorization_service import (
    authorization_to_context,
    issue_harness_authorization,
)
from app.services.production_execution_service import process_next_production_execution


def _active_goal(topic: str):
    goal = create_goal(
        goal_type="EVERGREEN",
        topic=topic,
        priority="HIGH",
        opportunity_score=9.0,
        target_duration="45s",
    )
    return set_goal_status(goal_id=goal["goal_id"], status="ACTIVE")


def _execution_context(goal_id: str):
    authorization = issue_harness_authorization(
        authorized_action="EXECUTION",
        subject="action:EXECUTION",
        lineage={
            "goal_id": goal_id,
            "zero_cost_operation": True,
            "purpose": "run-001-canary",
        },
    )
    return authorization, authorization_to_context(authorization)


def test_targeted_execution_ignores_other_active_goal_and_preserves_it():
    frozen = _active_goal("frozen-job18-goal")
    canary = _active_goal("independent-run001-canary")
    frozen_before = get_gta6_goal(frozen["goal_id"])

    authorization, context = _execution_context(canary["goal_id"])
    result = process_next_production_execution(
        context,
        goal_id=canary["goal_id"],
    )

    assert result["goal_id"] == canary["goal_id"]
    assert result["stage"] == "RESEARCH"
    assert result["status"] == "nothing_to_execute"
    assert authorization.execution_id == context["execution_id"]
    assert get_gta6_goal(frozen["goal_id"]) == frozen_before


def test_targeted_execution_fails_closed_on_goal_lineage_mismatch():
    first = _active_goal("first-goal")
    second = _active_goal("second-goal")
    _, context = _execution_context(first["goal_id"])

    with pytest.raises(PermissionError, match="goal_id lineage mismatch"):
        process_next_production_execution(
            context,
            goal_id=second["goal_id"],
        )


def test_untargeted_execution_rejects_goal_scoped_authorization():
    goal = _active_goal("scoped-goal")
    _, context = _execution_context(goal["goal_id"])

    with pytest.raises(PermissionError, match="did not target"):
        process_next_production_execution(context)
