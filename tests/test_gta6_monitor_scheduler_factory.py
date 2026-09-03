from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.gta6_monitor_apscheduler_adapter import (
    APSchedulerGTA6MonitorAdapter,
)
from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)
from app.services.gta6_monitor_scheduler import (
    GTA6MonitorScheduler,
)
from app.services.gta6_monitor_scheduler_factory import (
    create_gta6_monitor_scheduler,
)
from app.services.gta6_monitor_worker_service import (
    execute_gta6_monitor,
)


def test_factory_cria_scheduler_operacional():
    scheduler = create_gta6_monitor_scheduler()

    assert isinstance(
        scheduler,
        GTA6MonitorScheduler,
    )


def test_factory_cria_schedule_padrao():
    scheduler = create_gta6_monitor_scheduler()

    assert isinstance(
        scheduler.schedule,
        GTA6MonitorSchedule,
    )

    assert scheduler.schedule.interval_seconds == 300.0
    assert scheduler.schedule.timeout == 15.0
    assert scheduler.schedule.enabled is True
    assert scheduler.schedule.job_id == "gta6-monitor"


def test_factory_preserva_schedule_fornecido():
    schedule = GTA6MonitorSchedule(
        interval_seconds=120,
        timeout=30,
        enabled=False,
        job_id="gta6-monitor-test",
    )

    scheduler = create_gta6_monitor_scheduler(
        schedule=schedule,
    )

    assert scheduler.schedule is schedule


def test_factory_cria_adapter_apscheduler():
    scheduler = create_gta6_monitor_scheduler()

    assert isinstance(
        scheduler.adapter,
        APSchedulerGTA6MonitorAdapter,
    )


def test_factory_conecta_mesmo_schedule_ao_adapter():
    schedule = GTA6MonitorSchedule(
        interval_seconds=90,
        timeout=20,
    )

    scheduler = create_gta6_monitor_scheduler(
        schedule=schedule,
    )

    assert scheduler.adapter.schedule is schedule


def test_factory_conecta_worker_ao_adapter():
    scheduler = create_gta6_monitor_scheduler()

    assert scheduler.adapter.executor is execute_gta6_monitor


def test_factory_conecta_worker_ao_scheduler():
    scheduler = create_gta6_monitor_scheduler()

    assert scheduler.run_now.__self__ is scheduler


def test_factory_rejeita_schedule_invalido():
    with pytest.raises(
        ValueError,
        match="schedule must be a GTA6MonitorSchedule",
    ):
        create_gta6_monitor_scheduler(
            schedule="invalid",  # type: ignore[arg-type]
        )


def test_factory_nao_cria_apscheduler_antes_da_configuracao():
    scheduler = create_gta6_monitor_scheduler()

    assert scheduler.adapter.scheduler is None


def test_factory_run_now_executa_executor_configurado():
    expected = object()

    with patch(
        "app.services.gta6_monitor_scheduler_factory.execute_gta6_monitor",
        return_value=expected,
    ) as mocked_executor:
        scheduler = create_gta6_monitor_scheduler()

        result = scheduler.run_now()

    assert result is expected
    mocked_executor.assert_called_once_with()
