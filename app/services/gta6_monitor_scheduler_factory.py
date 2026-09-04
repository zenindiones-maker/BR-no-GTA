from __future__ import annotations

from app.services.gta6_monitor_apscheduler_adapter import (
    APSchedulerGTA6MonitorAdapter,
)
from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)
from app.services.gta6_monitor_scheduler import (
    GTA6MonitorScheduler,
)
from app.services.gta6_monitor_worker_service import (
    execute_gta6_monitor,
)
from app.services.gta6_scheduler_observability import (
    GTA6SchedulerObservability,
)


def create_gta6_monitor_scheduler(
    *,
    schedule: GTA6MonitorSchedule | None = None,
) -> GTA6MonitorScheduler:
    """Cria o scheduler operacional completo do monitor GTA6.

    A factory é o ponto de composição da infraestrutura de
    agendamento. Ela conecta:

        Schedule
            ↓
        Worker
            ↓
        APScheduler Adapter
            ↓
        Project Scheduler

    O scheduler da aplicação continua sem conhecer diretamente
    o APScheduler.
    """

    selected_schedule = schedule

    if selected_schedule is None:
        selected_schedule = GTA6MonitorSchedule()

    if not isinstance(
        selected_schedule,
        GTA6MonitorSchedule,
    ):
        raise ValueError(
            "schedule must be a GTA6MonitorSchedule"
        )

    observability = GTA6SchedulerObservability()

    adapter = APSchedulerGTA6MonitorAdapter(
        schedule=selected_schedule,
        executor=execute_gta6_monitor,
        observability=observability,
    )

    return GTA6MonitorScheduler(
        schedule=selected_schedule,
        executor=execute_gta6_monitor,
        adapter=adapter,
    )
