from __future__ import annotations

from typing import Callable

from app.services.gta6_monitor_schedule import (
    GTA6MonitorSchedule,
)


class APSchedulerGTA6MonitorAdapter:
    """Adapter do scheduler do projeto para a infraestrutura APScheduler.

    Esta classe define o contrato de infraestrutura utilizado pelo
    GTA6MonitorScheduler. A integração concreta com APScheduler será
    adicionada posteriormente, mantendo o domínio desacoplado da
    biblioteca de agendamento.
    """

    def __init__(
        self,
        *,
        schedule: GTA6MonitorSchedule,
        executor: Callable[[], object],
    ) -> None:
        if not isinstance(schedule, GTA6MonitorSchedule):
            raise ValueError(
                "schedule must be a GTA6MonitorSchedule"
            )

        if not callable(executor):
            raise ValueError(
                "executor must be callable"
            )

        self._schedule = schedule
        self._executor = executor

    @property
    def schedule(self) -> GTA6MonitorSchedule:
        """Retorna a configuração recebida pelo adapter."""
        return self._schedule

    @property
    def executor(self) -> Callable[[], object]:
        """Retorna o executor operacional configurado."""
        return self._executor

    def configure(self) -> None:
        """Configura o job na infraestrutura de agendamento."""
        raise NotImplementedError

    def start(self) -> None:
        """Inicia a infraestrutura de agendamento."""
        raise NotImplementedError

    def stop(self) -> None:
        """Interrompe a infraestrutura de agendamento."""
        raise NotImplementedError
