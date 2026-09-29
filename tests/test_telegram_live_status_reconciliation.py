from __future__ import annotations

from app.services.github_actions_run_tracker import GitHubActionsRunStatus
from app.services.telegram_conversation_service import classify_conversation_intent
from app.services.telegram_control_surface_status import derive_operational_activity_evidence
from app.services.telegram_status_reconciliation_service import (
    reconcile_remote_github_run_state,
)
from app.database.telegram_conversation_repository import (
    update_conversation_state,
)


class _Tracker:
    def __init__(self, status: GitHubActionsRunStatus):
        self.status = status
        self.calls = []

    def get_status(self, repository: str, run_id: int) -> GitHubActionsRunStatus:
        self.calls.append((repository, run_id))
        return self.status


def test_status_intent_understands_natural_operational_followups():
    for text in (
        "parou aí?",
        "parou ai",
        "travou?",
        "travou aí?",
        "ainda está rodando?",
        "ainda ta rodando?",
        "isso ainda está executando?",
    ):
        assert classify_conversation_intent(text) == "STATUS_REQUEST", text


def test_status_reconciles_completed_github_run_before_claiming_active_execution():
    chat_id = 1300801
    update_conversation_state(
        chat_id,
        active_goal_id="goal-system-recovery",
        active_task="continuous operation recovery",
        active_run_id="36587219010",
        active_stage="EXECUTING",
        execution_status="RUNNING",
        active_blocker=None,
        last_execution_result={
            "status": "RUNNING",
            "execution_id": "exec-36587219010",
            "run_id": "36587219010",
            "goal_id": "goal-system-recovery",
            "task_id": "continuous operation recovery",
        },
    )
    tracker = _Tracker(
        GitHubActionsRunStatus(
            run_id=36587219010,
            status="completed",
            conclusion="success",
        )
    )

    result = reconcile_remote_github_run_state(
        chat_id,
        tracker=tracker,
        repository="zenindiones-maker/BR-no-GTA",
    )

    assert result["attempted"] is True
    assert result["checked"] is True
    assert result["reconciled"] is True
    assert tracker.calls == [("zenindiones-maker/BR-no-GTA", 36587219010)]
    state = result["state"]
    assert state["execution_status"] == "COMPLETED"
    assert state["active_stage"] is None
    assert state["last_execution_result"]["status"] == "SUCCESS"
    assert state["last_execution_result"]["workflow_status"] == "COMPLETED"
    assert state["last_execution_result"]["workflow_conclusion"] == "SUCCESS"

    activity = derive_operational_activity_evidence(
        state,
        recent_authorizations=[],
    )
    assert activity["has_active_execution"] is False


def test_status_keeps_exact_remote_run_active_when_github_reports_in_progress():
    chat_id = 1300802
    update_conversation_state(
        chat_id,
        active_goal_id="goal-live",
        active_task="governed cloud execution",
        active_run_id="36596907553",
        active_stage="EXECUTING",
        execution_status="RUNNING",
        last_execution_result={
            "status": "RUNNING",
            "execution_id": "exec-36596907553",
            "run_id": "36596907553",
            "goal_id": "goal-live",
        },
    )
    tracker = _Tracker(
        GitHubActionsRunStatus(
            run_id=36596907553,
            status="in_progress",
            conclusion=None,
        )
    )

    result = reconcile_remote_github_run_state(
        chat_id,
        tracker=tracker,
        repository="zenindiones-maker/BR-no-GTA",
    )

    assert result["checked"] is True
    assert result["state"]["execution_status"] == "RUNNING"
    assert result["state"]["last_execution_result"]["status"] == "IN_PROGRESS"
    activity = derive_operational_activity_evidence(
        result["state"],
        recent_authorizations=[],
    )
    assert activity["has_active_execution"] is True
