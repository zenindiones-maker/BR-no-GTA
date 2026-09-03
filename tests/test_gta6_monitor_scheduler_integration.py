from unittest.mock import Mock

import pytest

from app.services.gta6_monitor_apscheduler_adapter import (
    APSchedulerGTA6MonitorAdapter,
)
from app.services.gta6_monitor_schedule import GTA6MonitorSchedule
from app.services.gta6_monitor_scheduler import GTA6MonitorScheduler


def test_scheduler_accepts_apscheduler_adapter():
    schedule = GTA6MonitorSchedule(
        interval_seconds=60,
        timeout=10,
        enabled=True,
        job_id="gta6-monitor-integration",
    )
    executor = Mock()
    adapter = Mock(spec=APSchedulerGTA6MonitorAdapter)

    scheduler = GTA6MonitorScheduler(
        schedule=schedule,
        executor=executor,
        adapter=adapter,
    )

    assert scheduler.schedule is schedule
    assert scheduler.adapter is adapter


def test_scheduler_rejects_invalid_adapter():
    schedule = GTA6MonitorSchedule()

    with pytest.raises(ValueError, match="adapter must be provided"):
        GTA6MonitorScheduler(
            schedule=schedule,
            executor=Mock(),
            adapter=None,
        )


def test_scheduler_configure_delegates_to_adapter():
    schedule = GTA6MonitorSchedule()
    executor = Mock()
    adapter = Mock(spec=APSchedulerGTA6MonitorAdapter)

    scheduler = GTA6MonitorScheduler(
        schedule=schedule,
        executor=executor,
        adapter=adapter,
    )

    scheduler.configure()

    adapter.configure.assert_called_once_with()


def test_scheduler_start_delegates_to_adapter():
    schedule = GTA6MonitorSchedule()
    executor = Mock()
    adapter = Mock(spec=APSchedulerGTA6MonitorAdapter)

    scheduler = GTA6MonitorScheduler(
        schedule=schedule,
        executor=executor,
        adapter=adapter,
    )

    scheduler.start()

    adapter.start.assert_called_once_with()


def test_scheduler_stop_delegates_to_adapter():
    schedule = GTA6MonitorSchedule()
    executor = Mock()
    adapter = Mock(spec=APSchedulerGTA6MonitorAdapter)

    scheduler = GTA6MonitorScheduler(
        schedule=schedule,
        executor=executor,
        adapter=adapter,
    )

    scheduler.stop()

    adapter.stop.assert_called_once_with()


def test_scheduler_run_now_executes_executor():
    schedule = GTA6MonitorSchedule()
    executor = Mock(return_value="executed")
    adapter = Mock(spec=APSchedulerGTA6MonitorAdapter)

    scheduler = GTA6MonitorScheduler(
        schedule=schedule,
        executor=executor,
        adapter=adapter,
    )

    result = scheduler.run_now()

    assert result == "executed"
    executor.assert_called_once_with()


def test_scheduler_does_not_call_adapter_for_run_now():
    schedule = GTA6MonitorSchedule()
    executor = Mock()
    adapter = Mock(spec=APSchedulerGTA6MonitorAdapter)

    scheduler = GTA6MonitorScheduler(
        schedule=schedule,
        executor=executor,
        adapter=adapter,
    )

    scheduler.run_now()

    adapter.configure.assert_not_called()
    adapter.start.assert_not_called()
    adapter.stop.assert_not_called()


def test_scheduler_exposes_only_project_scheduler_contract():
    schedule = GTA6MonitorSchedule()
    executor = Mock()
    adapter = Mock(spec=APSchedulerGTA6MonitorAdapter)

    scheduler = GTA6MonitorScheduler(
        schedule=schedule,
        executor=executor,
        adapter=adapter,
    )

    assert hasattr(scheduler, "configure")
    assert hasattr(scheduler, "start")
    assert hasattr(scheduler, "stop")
    assert hasattr(scheduler, "run_now")
