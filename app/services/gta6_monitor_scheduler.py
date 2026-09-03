from __future__ import annotations

from typing import Any, Callable

from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)


_MISSING = object()


class GTA6MonitorScheduler:
    """Orquestra o ciclo de vida do agendamento do monitor GTA6.

    O scheduler pertence à aplicação e não conhece detalhes da
    infraestrutura de temporização. Essa responsabilidade fica
    encapsulada no adapter recebido durante a construção.
    """

    def __init__(
        self,
        *,
        schedule: GTA6MonitorSchedule,
        executor: Callable[[], object],
        adapter: Any = _MISSING,
    ) -> None:
        if not isinstance(schedule, GTA6MonitorSchedule):
            raise ValueError(
                "schedule must be a GTA6MonitorSchedule"
            )

        if not callable(executor):
            raise ValueError(
                "executor must be callable"
            )

        if adapter is None:
            raise ValueError(
                "adapter must be provided"
            )

        self._schedule = schedule
        self._executor = executor
        self._adapter = (
            None
            if adapter is _MISSING
            else adapter
        )

    @property
    def schedule(self) -> GTA6MonitorSchedule:
        """Retorna a configuração do agendamento."""
        return self._schedule

    @property
    def adapter(self) -> Any:
        """Retorna o adapter de infraestrutura configurado."""
        return self._adapter

    def configure(self) -> None:
        """Configura o agendamento através do adapter."""
        if self._adapter is None:
            return

        self._adapter.configure()

    def start(self) -> None:
        """Inicia o agendamento através do adapter."""
        if self._adapter is None:
            return

        self._adapter.start()

    def stop(self) -> None:
        """Interrompe o agendamento através do adapter."""
        if self._adapter is None:
            return

        self._adapter.stop()

    def run_now(self) -> object:
        """Executa imediatamente o executor, sem passar pelo adapter."""
        return self._executor()
