from __future__ import annotations

from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler

from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)


class APSchedulerGTA6MonitorAdapter:
    """Adapter entre o contrato do monitor GTA6 e o APScheduler."""

    def __init__(
        self,
        *,
        schedule: GTA6MonitorSchedule,
        executor: Callable[[], object],
        scheduler: Any | None = None,
    ) -> None:
        if not isinstance(schedule, GTA6MonitorSchedule):
            raise ValueError(
                "schedule must be a GTA6MonitorSchedule"
            )

        if not callable(executor):
            raise ValueError("executor must be callable")

        self._schedule = schedule
        self._executor = executor
        self._scheduler = (
            scheduler
            if scheduler is not None
            else BackgroundScheduler()
        )

    @property
    def schedule(self) -> GTA6MonitorSchedule:
        """Retorna a configuração do agendamento."""
        return self._schedule

    def configure(self) -> None:
        """Registra o job no APScheduler quando o agendamento está ativo."""
        if not self._schedule.enabled:
            return

        self._scheduler.add_job(
            self._executor,
            trigger="interval",
            seconds=float(self._schedule.interval_seconds),
            id=self._schedule.job_id,
        )

    def start(self) -> None:
        """Inicia o scheduler subjacente."""
        self._scheduler.start()

    def stop(self) -> None:
        """Encerra o scheduler subjacente."""
        self._scheduler.shutdown()
