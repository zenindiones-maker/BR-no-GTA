import json

import pytest

from app.services.github_actions_run_tracker import (
    GitHubActionsProofObservation,
    GitHubActionsRunTracker,
    classify_github_actions_proof,
)


class FakeCommandRunner:
    def __init__(self, output: str) -> None:
        self.output = output
        self.commands: list[list[str]] = []

    def __call__(self, command):
        self.commands.append(list(command))
        return self.output


def test_tracker_requires_command_runner():
    with pytest.raises(
        ValueError,
        match="executor de comandos GitHub",
    ):
        GitHubActionsRunTracker(None)


def test_tracker_requires_repository():
    runner = FakeCommandRunner(
        '{"status":"queued","conclusion":null}'
    )
    tracker = GitHubActionsRunTracker(runner)

    with pytest.raises(
        ValueError,
        match="repositório GitHub",
    ):
        tracker.get_status("", 123456789)


def test_tracker_requires_positive_run_id():
    runner = FakeCommandRunner(
        '{"status":"queued","conclusion":null}'
    )
    tracker = GitHubActionsRunTracker(runner)

    with pytest.raises(
        ValueError,
        match="run_id",
    ):
        tracker.get_status(
            "zenindiones-maker/BR-no-GTA",
            0,
        )


@pytest.mark.parametrize(
    "status,conclusion",
    [
        ("queued", None),
        ("in_progress", None),
        ("completed", "success"),
        ("completed", "failure"),
        ("completed", "cancelled"),
        ("completed", "timed_out"),
        ("completed", "action_required"),
        ("completed", "neutral"),
        ("completed", "skipped"),
        ("completed", "stale"),
    ],
)
def test_tracker_reads_status_and_conclusion(
    status,
    conclusion,
):
    runner = FakeCommandRunner(
        json.dumps(
            {
                "status": status,
                "conclusion": conclusion,
            }
        )
    )

    tracker = GitHubActionsRunTracker(runner)

    result = tracker.get_status(
        "zenindiones-maker/BR-no-GTA",
        123456789,
    )

    assert result.run_id == 123456789
    assert result.status == status
    assert result.conclusion == conclusion

    assert runner.commands == [
        [
            "gh",
            "run",
            "view",
            "123456789",
            "--repo",
            "zenindiones-maker/BR-no-GTA",
            "--json",
            "status,conclusion",
        ]
    ]


def test_tracker_detects_success():
    runner = FakeCommandRunner(
        '{"status":"completed","conclusion":"success"}'
    )
    tracker = GitHubActionsRunTracker(runner)

    result = tracker.get_status(
        "zenindiones-maker/BR-no-GTA",
        123456789,
    )

    assert result.completed is True
    assert result.succeeded is True
    assert result.failed is False
    assert result.cancelled is False


def test_tracker_detects_failure():
    runner = FakeCommandRunner(
        '{"status":"completed","conclusion":"failure"}'
    )
    tracker = GitHubActionsRunTracker(runner)

    result = tracker.get_status(
        "zenindiones-maker/BR-no-GTA",
        123456789,
    )

    assert result.completed is True
    assert result.succeeded is False
    assert result.failed is True
    assert result.cancelled is False


def test_tracker_detects_cancelled():
    runner = FakeCommandRunner(
        '{"status":"completed","conclusion":"cancelled"}'
    )
    tracker = GitHubActionsRunTracker(runner)

    result = tracker.get_status(
        "zenindiones-maker/BR-no-GTA",
        123456789,
    )

    assert result.completed is True
    assert result.succeeded is False
    assert result.failed is False
    assert result.cancelled is True


def test_tracker_queued_is_not_completed():
    runner = FakeCommandRunner(
        '{"status":"queued","conclusion":null}'
    )
    tracker = GitHubActionsRunTracker(runner)

    result = tracker.get_status(
        "zenindiones-maker/BR-no-GTA",
        123456789,
    )

    assert result.completed is False
    assert result.succeeded is False
    assert result.failed is False
    assert result.cancelled is False


def test_tracker_rejects_empty_output():
    runner = FakeCommandRunner("")
    tracker = GitHubActionsRunTracker(runner)

    with pytest.raises(
        RuntimeError,
        match="não retornou o estado",
    ):
        tracker.get_status(
            "zenindiones-maker/BR-no-GTA",
            123456789,
        )


def test_tracker_rejects_invalid_json():
    runner = FakeCommandRunner(
        "isso não é json"
    )
    tracker = GitHubActionsRunTracker(runner)

    with pytest.raises(
        RuntimeError,
        match="JSON válido",
    ):
        tracker.get_status(
            "zenindiones-maker/BR-no-GTA",
            123456789,
        )


def test_tracker_requires_status():
    runner = FakeCommandRunner(
        '{"conclusion":"success"}'
    )
    tracker = GitHubActionsRunTracker(runner)

    with pytest.raises(
        RuntimeError,
        match="status do run",
    ):
        tracker.get_status(
            "zenindiones-maker/BR-no-GTA",
            123456789,
        )


def _proof_observation(
    *,
    status="completed",
    conclusion="success",
    head_sha="head-new",
    workflow=".github/workflows/real-agent-self-improvement.yml",
    branch="work/gate6f-analytics-learning",
    run_attempt=1,
    evidence_valid=True,
):
    return GitHubActionsProofObservation(
        run_id=42,
        status=status,
        conclusion=conclusion,
        head_sha=head_sha,
        workflow=workflow,
        branch=branch,
        run_attempt=run_attempt,
        evidence_valid=evidence_valid,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("requested", "CREATED_NOT_YET_QUEUED"),
        ("queued", "QUEUED_FOR_RUNNER"),
        ("pending", "WAITING_FOR_CONCURRENCY"),
        ("waiting", "WAITING_FOR_ENVIRONMENT_OR_PROTECTION"),
        ("in_progress", "EXECUTING"),
        ("completed", "TERMINAL_GITHUB_RUN"),
    ],
)
def test_raw_github_lifecycle_projection(raw, expected):
    runner = FakeCommandRunner(json.dumps({"status": raw, "conclusion": None}))
    result = GitHubActionsRunTracker(runner).get_status(
        "zenindiones-maker/BR-no-GTA", 123456789
    )
    assert result.status == raw
    assert result.operational_state == expected


@pytest.mark.parametrize(
    ("status", "expected_result"),
    [
        ("requested", "NOT_STARTED"),
        ("queued", "WAITING"),
        ("pending", "WAITING"),
        ("waiting", "WAITING"),
        ("in_progress", "EXECUTING"),
    ],
)
def test_nonterminal_states_never_prove(status, expected_result):
    result = classify_github_actions_proof(
        _proof_observation(status=status, conclusion=None),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
    )
    assert result.proof_result == expected_result
    assert result.current_head_proven is False
    assert result.mission_failure is False


def test_pending_is_waiting_for_concurrency():
    result = classify_github_actions_proof(
        _proof_observation(status="pending", conclusion=None),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
    )
    assert result.operational_state == "WAITING_FOR_CONCURRENCY"
    assert result.proof_result == "WAITING"


def test_waiting_is_not_automatic_human_gate():
    result = classify_github_actions_proof(
        _proof_observation(status="waiting", conclusion=None),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
    )
    assert result.operational_state == "WAITING_FOR_ENVIRONMENT_OR_PROTECTION"
    assert result.mission_failure is False


def test_completed_success_current_head_can_prove():
    result = classify_github_actions_proof(
        _proof_observation(),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
        evidence_required=True,
    )
    assert result.proof_relevance == "CURRENT_HEAD"
    assert result.proof_result == "PASS"
    assert result.current_head_proven is True


def test_completed_success_old_head_cannot_prove_current():
    result = classify_github_actions_proof(
        _proof_observation(head_sha="head-old"),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
    )
    assert result.proof_relevance == "HISTORICAL"
    assert result.proof_result == "NON_PROVING"


def test_completed_failure_cannot_prove():
    result = classify_github_actions_proof(
        _proof_observation(conclusion="failure"),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
    )
    assert result.proof_result == "FAIL"
    assert result.current_head_proven is False
    assert result.mission_failure is True


def test_superseded_cancelled_old_head_not_mission_failure():
    result = classify_github_actions_proof(
        _proof_observation(conclusion="cancelled", head_sha="head-old"),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
    )
    assert result.proof_relevance == "SUPERSEDED"
    assert result.terminal_outcome == "CANCELLED"
    assert result.proof_result == "NON_PROVING"
    assert result.mission_failure is False


def test_rerun_old_sha_not_current_head_proof():
    result = classify_github_actions_proof(
        _proof_observation(head_sha="head-old", run_attempt=2),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
    )
    assert result.proof_result == "NON_PROVING"
    assert result.current_head_proven is False


@pytest.mark.parametrize(
    ("field", "override"),
    [
        ("workflow", ".github/workflows/other.yml"),
        ("branch", "main"),
        ("run_attempt", None),
        ("evidence_valid", False),
    ],
)
def test_current_head_match_and_exact_scope_required(field, override):
    result = classify_github_actions_proof(
        _proof_observation(**{field: override}),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
        evidence_required=True,
    )
    assert result.current_head_proven is False
    assert result.proof_result == "NON_PROVING"


@pytest.mark.parametrize(
    ("conclusion", "terminal"),
    [
        ("timed_out", "FAILURE_TIMEOUT"),
        ("action_required", "EXTERNAL_ACTION_STATE"),
        ("stale", "NON_PROVING_STALE"),
        ("skipped", "NON_PROVING_SKIPPED"),
        ("neutral", "NON_PROVING"),
    ],
)
def test_completed_conclusion_is_not_implicitly_green(conclusion, terminal):
    result = classify_github_actions_proof(
        _proof_observation(conclusion=conclusion),
        remote_head="head-new",
        expected_workflow=".github/workflows/real-agent-self-improvement.yml",
        expected_branch="work/gate6f-analytics-learning",
    )
    assert result.terminal_outcome == terminal
    assert result.current_head_proven is False
