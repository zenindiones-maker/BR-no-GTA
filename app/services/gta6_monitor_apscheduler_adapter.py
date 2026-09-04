from __future__ import annotations

from typing import Callable

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MAX_INSTANCES,
    EVENT_JOB_MISSED,
)
from apscheduler.schedulers.background import BackgroundScheduler

from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)
from app.services.gta6_scheduler_observability import (
    GTA6SchedulerObservability,
    create_scheduler_event_listener,
)


class APSchedulerGTA6MonitorAdapter:
    """Adapter entre o scheduler do projeto e o APScheduler 3.x.

    O projeto conhece apenas o contrato do adapter. Os detalhes da
    infraestrutura APScheduler permanecem encapsulados nesta classe.
    """

    def __init__(
        self,
        *,
        schedule: GTA6MonitorSchedule,
        executor: Callable[[], object],
        observability: GTA6SchedulerObservability | None = None,
    ) -> None:
        if not isinstance(schedule, GTA6MonitorSchedule):
            raise ValueError(
                "schedule must be a GTA6MonitorSchedule"
            )

        if not callable(executor):
            raise ValueError(
                "executor must be callable"
            )

        if observability is not None and not isinstance(
            observability,
            GTA6SchedulerObservability,
        ):
            raise ValueError(
                "observability must be a GTA6SchedulerObservability"
            )

        self._schedule = schedule
        self._executor = executor
        self._observability = (
            observability or GTA6SchedulerObservability()
        )
        self._scheduler: BackgroundScheduler | None = None
        self._listener_registered = False

    @property
    def schedule(self) -> GTA6MonitorSchedule:
        """Retorna a configuração recebida pelo adapter."""
        return self._schedule

    @property
    def executor(self) -> Callable[[], object]:
        """Retorna o executor operacional configurado."""
        return self._executor

    @property
    def scheduler(self) -> BackgroundScheduler | None:
        """Retorna a instância do APScheduler configurada."""
        return self._scheduler

    @property
    def observability(self) -> GTA6SchedulerObservability:
        """Retorna o componente de observabilidade configurado."""
        return self._observability

    def configure(self) -> None:
        """Cria o scheduler e registra o job do monitor GTA6."""

        if self._scheduler is None:
            self._scheduler = BackgroundScheduler()

        if not self._listener_registered:
            self._scheduler.add_listener(
                create_scheduler_event_listener(
                    self._observability,
                ),
                EVENT_JOB_EXECUTED
                | EVENT_JOB_ERROR
                | EVENT_JOB_MISSED
                | EVENT_JOB_MAX_INSTANCES,
            )
            self._listener_registered = True

        if not self._schedule.enabled:
            return

        self._scheduler.add_job(
            self._executor,
            trigger="interval",
            seconds=self._schedule.interval_seconds,
            id=self._schedule.job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=self._schedule.misfire_grace_time,
        )

    def start(self) -> None:
        """Inicia o scheduler previamente configurado."""

        if self._scheduler is None:
            raise RuntimeError(
                "scheduler is not configured"
            )

        if self._schedule.enabled:
            self._scheduler.start()

    def stop(self) -> None:
        """Interrompe o scheduler quando ele estiver configurado."""

        if self._scheduler is None:
            return

        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
