import json

import pytest

from app.services.github_actions_run_tracker import (
    GitHubActionsRunTracker,
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
