from unittest.mock import Mock, patch

import pytest

from app.services.gta6_monitor_apscheduler_adapter import (
    APSchedulerGTA6MonitorAdapter,
)
from app.services.gta6_monitor_schedule import GTA6MonitorSchedule


def test_adapter_accepts_valid_schedule_and_executor():
    schedule = GTA6MonitorSchedule(
        interval_seconds=60,
        timeout=10,
        enabled=True,
        job_id="gta6-monitor-adapter",
    )
    executor = Mock()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=schedule,
        executor=executor,
    )

    assert adapter.schedule is schedule
    assert adapter.executor is executor


def test_adapter_rejects_invalid_schedule():
    with pytest.raises(
        ValueError,
        match="schedule must be a GTA6MonitorSchedule",
    ):
        APSchedulerGTA6MonitorAdapter(
            schedule=Mock(),
            executor=Mock(),
        )


def test_adapter_rejects_non_callable_executor():
    schedule = GTA6MonitorSchedule()

    with pytest.raises(
        ValueError,
        match="executor must be callable",
    ):
        APSchedulerGTA6MonitorAdapter(
            schedule=schedule,
            executor=None,
        )


def test_adapter_configure_creates_and_registers_scheduler_job():
    schedule = GTA6MonitorSchedule(
        interval_seconds=60,
        timeout=10,
        enabled=True,
        job_id="gta6-monitor-adapter",
    )
    executor = Mock()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=schedule,
        executor=executor,
    )

    with patch(
        "app.services.gta6_monitor_apscheduler_adapter.BackgroundScheduler"
    ) as scheduler_class:
        scheduler = scheduler_class.return_value

        adapter.configure()

        scheduler_class.assert_called_once_with()
        scheduler.add_job.assert_called_once()

        call = scheduler.add_job.call_args
        assert call.kwargs["id"] == schedule.job_id
        assert call.kwargs["seconds"] == schedule.interval_seconds
        assert call.kwargs["replace_existing"] is True
        assert call.args[0] is executor


def test_adapter_configure_does_not_register_job_when_disabled():
    schedule = GTA6MonitorSchedule(
        interval_seconds=60,
        timeout=10,
        enabled=False,
        job_id="gta6-monitor-disabled",
    )
    executor = Mock()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=schedule,
        executor=executor,
    )

    with patch(
        "app.services.gta6_monitor_apscheduler_adapter.BackgroundScheduler"
    ) as scheduler_class:
        scheduler = scheduler_class.return_value

        adapter.configure()

        scheduler.add_job.assert_not_called()


def test_adapter_configure_is_idempotent_for_scheduler_creation():
    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
    )

    with patch(
        "app.services.gta6_monitor_apscheduler_adapter.BackgroundScheduler"
    ) as scheduler_class:
        scheduler = scheduler_class.return_value

        adapter.configure()
        adapter.configure()

        scheduler_class.assert_called_once_with()
        assert scheduler.add_job.call_count == 2


def test_adapter_start_starts_scheduler():
    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
    )

    with patch(
        "app.services.gta6_monitor_apscheduler_adapter.BackgroundScheduler"
    ) as scheduler_class:
        scheduler = scheduler_class.return_value

        adapter.configure()
        adapter.start()

        scheduler.start.assert_called_once_with()


def test_adapter_stop_stops_scheduler():
    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
    )

    with patch(
        "app.services.gta6_monitor_apscheduler_adapter.BackgroundScheduler"
    ) as scheduler_class:
        scheduler = scheduler_class.return_value

        adapter.configure()
        adapter.stop()

        scheduler.shutdown.assert_called_once_with(wait=True)


def test_adapter_start_requires_configuration():
    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
    )

    with pytest.raises(
        RuntimeError,
        match="scheduler is not configured",
    ):
        adapter.start()


def test_adapter_stop_is_safe_before_configuration():
    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
    )

    adapter.stop()


def test_adapter_exposes_scheduler_after_configuration():
    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
    )

    assert adapter.scheduler is None

    with patch(
        "app.services.gta6_monitor_apscheduler_adapter.BackgroundScheduler"
    ) as scheduler_class:
        scheduler = scheduler_class.return_value

        adapter.configure()

        assert adapter.scheduler is scheduler


def test_configure_limits_monitor_to_one_concurrent_instance():
    from unittest.mock import Mock

    executor = Mock()
    scheduler = Mock()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(
            interval_seconds=300,
        ),
        executor=executor,
    )

    adapter._scheduler = scheduler

    adapter.configure()

    scheduler.add_job.assert_called_once_with(
        executor,
        trigger="interval",
        seconds=300,
        id="gta6-monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

def test_configure_coalesces_missed_monitor_runs():
    from unittest.mock import Mock

    executor = Mock()
    scheduler = Mock()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(
            interval_seconds=300,
        ),
        executor=executor,
    )

    adapter._scheduler = scheduler

    adapter.configure()

    scheduler.add_job.assert_called_once_with(
        executor,
        trigger="interval",
        seconds=300,
        id="gta6-monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
def test_configure_sets_misfire_grace_time():
    from unittest.mock import Mock

    executor = Mock()
    scheduler = Mock()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(
            interval_seconds=300,
        ),
        executor=executor,
    )

    adapter._scheduler = scheduler

    adapter.configure()

    scheduler.add_job.assert_called_once_with(
        executor,
        trigger="interval",
        seconds=300,
        id="gta6-monitor",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
