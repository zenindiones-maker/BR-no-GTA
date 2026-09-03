from unittest.mock import Mock

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


def test_adapter_configure_is_infrastructure_extension_point():
    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
    )

    with pytest.raises(NotImplementedError):
        adapter.configure()


def test_adapter_start_is_infrastructure_extension_point():
    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
    )

    with pytest.raises(NotImplementedError):
        adapter.start()


def test_adapter_stop_is_infrastructure_extension_point():
    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=GTA6MonitorSchedule(),
        executor=Mock(),
    )

    with pytest.raises(NotImplementedError):
        adapter.stop()
