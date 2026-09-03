from __future__ import annotations

from typing import Callable

from app.services.gta6_monitor_schedule import GTA6MonitorSchedule


class GTA6MonitorScheduler:
    """Controla o agendamento operacional do monitor GTA6.

    A implementação concreta de temporização fica isolada atrás
    deste contrato. O scheduler conhece apenas a configuração e
    a função operacional que deve ser disparada.
    """

    def __init__(
        self,
        *,
        schedule: GTA6MonitorSchedule,
        executor: Callable[[], object],
    ) -> None:
        if not isinstance(schedule, GTA6MonitorSchedule):
            raise ValueError("schedule must be a GTA6MonitorSchedule")

        if not callable(executor):
            raise ValueError("executor must be callable")

        self._schedule = schedule
        self._executor = executor

    @property
    def schedule(self) -> GTA6MonitorSchedule:
        """Retorna a configuração do agendamento."""
        return self._schedule

    def run_now(self) -> object:
        """Executa imediatamente o executor configurado."""
        return self._executor()
