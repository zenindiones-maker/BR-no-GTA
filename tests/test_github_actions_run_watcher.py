import pytest

from app.services.github_actions_run_tracker import (
    GitHubActionsRunStatus,
)
from app.services.github_actions_run_watcher import (
    GitHubActionsRunWatcher,
)


class FakeRunTracker:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = []

    def get_status(self, repository, run_id):
        self.calls.append(
            {
                "repository": repository,
                "run_id": run_id,
            }
        )

        if not self.statuses:
            raise AssertionError(
                "O FakeRunTracker ficou sem estados."
            )

        return self.statuses.pop(0)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def status(status, conclusion=None):
    return GitHubActionsRunStatus(
        run_id=123456789,
        status=status,
        conclusion=conclusion,
    )


def test_watcher_returns_success_after_completion():
    tracker = FakeRunTracker(
        [
            status("queued"),
            status("in_progress"),
            status("completed", "success"),
        ]
    )

    clock = FakeClock()

    watcher = GitHubActionsRunWatcher(
        tracker=tracker,
        poll_interval=5.0,
        timeout=60.0,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    result = watcher.wait_for_completion(
        repository="zenindiones-maker/BR-no-GTA",
        run_id=123456789,
    )

    assert result.run_id == 123456789
    assert result.status == "completed"
    assert result.conclusion == "success"
    assert result.timed_out is False
    assert result.succeeded is True
    assert result.failed is False
    assert result.cancelled is False

    assert clock.sleeps == [5.0, 5.0]


@pytest.mark.parametrize(
    "conclusion,expected_failed,expected_cancelled",
    [
        ("failure", True, False),
        ("timed_out", True, False),
        ("action_required", True, False),
        ("cancelled", False, True),
        ("neutral", False, False),
        ("skipped", False, False),
        ("stale", False, False),
    ],
)
def test_watcher_returns_final_conclusion(
    conclusion,
    expected_failed,
    expected_cancelled,
):
    tracker = FakeRunTracker(
        [
            status("in_progress"),
            status("completed", conclusion),
        ]
    )

    clock = FakeClock()

    watcher = GitHubActionsRunWatcher(
        tracker=tracker,
        poll_interval=5.0,
        timeout=60.0,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    result = watcher.wait_for_completion(
        repository="zenindiones-maker/BR-no-GTA",
        run_id=123456789,
    )

    assert result.status == "completed"
    assert result.conclusion == conclusion
    assert result.timed_out is False
    assert result.failed is expected_failed
    assert result.cancelled is expected_cancelled


def test_watcher_times_out_without_blocking_forever():
    tracker = FakeRunTracker(
        [
            status("queued"),
            status("in_progress"),
            status("in_progress"),
            status("in_progress"),
        ]
    )

    clock = FakeClock()

    watcher = GitHubActionsRunWatcher(
        tracker=tracker,
        poll_interval=5.0,
        timeout=12.0,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    result = watcher.wait_for_completion(
        repository="zenindiones-maker/BR-no-GTA",
        run_id=123456789,
    )

    assert result.run_id == 123456789
    assert result.status == "in_progress"
    assert result.conclusion is None
    assert result.timed_out is True

    assert result.succeeded is False
    assert result.failed is False
    assert result.cancelled is False

    assert clock.sleeps == [5.0, 5.0, 2.0]
    assert clock.now == 12.0


def test_watcher_does_not_sleep_after_completion():
    tracker = FakeRunTracker(
        [
            status("completed", "success"),
        ]
    )

    clock = FakeClock()

    watcher = GitHubActionsRunWatcher(
        tracker=tracker,
        poll_interval=5.0,
        timeout=60.0,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    result = watcher.wait_for_completion(
        repository="zenindiones-maker/BR-no-GTA",
        run_id=123456789,
    )

    assert result.succeeded is True
    assert clock.sleeps == []


def test_watcher_requires_tracker():
    with pytest.raises(
        ValueError,
        match="RunTracker",
    ):
        GitHubActionsRunWatcher(
            tracker=None,
        )


@pytest.mark.parametrize(
    "poll_interval,timeout",
    [
        (0, 60),
        (-1, 60),
        (5, 0),
        (5, -1),
    ],
)
def test_watcher_requires_positive_timing(
    poll_interval,
    timeout,
):
    tracker = FakeRunTracker([])

    with pytest.raises(ValueError):
        GitHubActionsRunWatcher(
            tracker=tracker,
            poll_interval=poll_interval,
            timeout=timeout,
        )


def test_watcher_requires_repository():
    tracker = FakeRunTracker([])
    clock = FakeClock()

    watcher = GitHubActionsRunWatcher(
        tracker=tracker,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    with pytest.raises(
        ValueError,
        match="repositório GitHub",
    ):
        watcher.wait_for_completion(
            repository="",
            run_id=123456789,
        )


def test_watcher_requires_positive_run_id():
    tracker = FakeRunTracker([])
    clock = FakeClock()

    watcher = GitHubActionsRunWatcher(
        tracker=tracker,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )

    with pytest.raises(
        ValueError,
        match="run_id",
    ):
        watcher.wait_for_completion(
            repository="zenindiones-maker/BR-no-GTA",
            run_id=0,
        )
