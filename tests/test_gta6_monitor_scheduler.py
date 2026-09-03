from unittest.mock import Mock

import pytest

from app.services.gta6_monitor_schedule import GTA6MonitorSchedule
from app.services.gta6_monitor_scheduler import GTA6MonitorScheduler


def test_scheduler_accepts_valid_schedule_and_executor():
    executor = Mock()
    schedule = GTA6MonitorSchedule()

    scheduler = GTA6MonitorScheduler(
        schedule=schedule,
        executor=executor,
    )

    assert scheduler.schedule is schedule


def test_scheduler_rejects_invalid_schedule():
    with pytest.raises(
        ValueError,
        match="schedule must be a GTA6MonitorSchedule",
    ):
        GTA6MonitorScheduler(
            schedule=None,
            executor=Mock(),
        )


@pytest.mark.parametrize(
    "executor",
    [None, 123, "executor", object()],
)
def test_scheduler_rejects_non_callable_executor(executor):
    with pytest.raises(
        ValueError,
        match="executor must be callable",
    ):
        GTA6MonitorScheduler(
            schedule=GTA6MonitorSchedule(),
            executor=executor,
        )


def test_run_now_delegates_to_executor():
    result = object()
    executor = Mock(return_value=result)

    scheduler = GTA6MonitorScheduler(
        schedule=GTA6MonitorSchedule(),
        executor=executor,
    )

    returned = scheduler.run_now()

    assert returned is result
    executor.assert_called_once_with()


def test_run_now_does_not_add_scheduler_logic():
    executor = Mock(return_value="monitor-result")

    scheduler = GTA6MonitorScheduler(
        schedule=GTA6MonitorSchedule(
            interval_seconds=60,
            timeout=10,
            enabled=False,
            job_id="test-monitor",
        ),
        executor=executor,
    )

    assert scheduler.run_now() == "monitor-result"
    executor.assert_called_once_with()
