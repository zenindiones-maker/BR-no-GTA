from unittest.mock import Mock

import pytest

from app.services.gta6_monitor_schedule import GTA6MonitorSchedule


def test_adapter_module_can_be_imported():
    from app.services.gta6_monitor_apscheduler_adapter import (
        APSchedulerGTA6MonitorAdapter,
    )

    assert APSchedulerGTA6MonitorAdapter is not None


def test_adapter_requires_schedule():
    from app.services.gta6_monitor_apscheduler_adapter import (
        APSchedulerGTA6MonitorAdapter,
    )

    with pytest.raises(
        ValueError,
        match="schedule must be a GTA6MonitorSchedule",
    ):
        APSchedulerGTA6MonitorAdapter(
            schedule=None,
            executor=Mock(),
        )


def test_adapter_requires_callable_executor():
    from app.services.gta6_monitor_apscheduler_adapter import (
        APSchedulerGTA6MonitorAdapter,
    )

    with pytest.raises(
        ValueError,
        match="executor must be callable",
    ):
        APSchedulerGTA6MonitorAdapter(
            schedule=GTA6MonitorSchedule(),
            executor=None,
        )


def test_adapter_accepts_valid_configuration():
    from app.services.gta6_monitor_apscheduler_adapter import (
        APSchedulerGTA6MonitorAdapter,
    )

    schedule = GTA6MonitorSchedule(
        interval_seconds=60,
        timeout=10,
        enabled=True,
        job_id="gta6-monitor-test",
    )
    executor = Mock()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=schedule,
        executor=executor,
    )

    assert adapter.schedule is schedule


def test_disabled_schedule_does_not_register_job():
    from app.services.gta6_monitor_apscheduler_adapter import (
        APSchedulerGTA6MonitorAdapter,
    )

    scheduler = Mock()
    schedule = GTA6MonitorSchedule(enabled=False)

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=schedule,
        executor=Mock(),
        scheduler=scheduler,
    )

    adapter.configure()

    scheduler.add_job.assert_not_called()


def test_enabled_schedule_registers_interval_job():
    from app.services.gta6_monitor_apscheduler_adapter import (
        APSchedulerGTA6MonitorAdapter,
    )

    scheduler = Mock()
    executor = Mock()
    schedule = GTA6MonitorSchedule(
        interval_seconds=60,
        enabled=True,
        job_id="gta6-monitor-test",
    )

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=schedule,
        executor=executor,
        scheduler=scheduler,
    )

    adapter.configure()

    scheduler.add_job.assert_called_once()
    kwargs = scheduler.add_job.call_args.kwargs

    assert kwargs["trigger"] == "interval"
    assert kwargs["seconds"] == 60.0
    assert kwargs["id"] == "gta6-monitor-test"


def test_start_delegates_to_scheduler():
    from app.services.gta6_monitor_apscheduler_adapter import (
        APSchedulerGTA6MonitorAdapter,
    )

    scheduler = Mock()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
        scheduler=scheduler,
    )

    adapter.start()

    scheduler.start.assert_called_once_with()


def test_stop_delegates_to_scheduler():
    from app.services.gta6_monitor_apscheduler_adapter import (
        APSchedulerGTA6MonitorAdapter,
    )

    scheduler = Mock()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
        scheduler=scheduler,
    )

    adapter.stop()

    scheduler.shutdown.assert_called_once_with()
