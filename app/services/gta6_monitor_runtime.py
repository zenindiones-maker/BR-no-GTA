from __future__ import annotations

from typing import Any


class GTA6MonitorRuntime:
    """Gerencia o ciclo de vida operacional do monitor GTA6.

    O Runtime não conhece APScheduler nem detalhes de execução do
    monitor. Ele apenas controla o ciclo de vida do scheduler da
    aplicação.
    """

    def __init__(
        self,
        *,
        scheduler: Any,
    ) -> None:
        if scheduler is None:
            raise ValueError(
                "scheduler must be provided"
            )

        self._scheduler = scheduler
        self._running = False

    @property
    def scheduler(self) -> Any:
        return self._scheduler

    @property
    def running(self) -> bool:
        """Indica se o Runtime está atualmente em execução."""
        return self._running

    def start(self) -> None:
        """Configura e inicia o scheduler do monitor."""
        if self._running:
            return

        self._scheduler.configure()
        self._scheduler.start()
        self._running = True

    def stop(self) -> None:
        """Solicita a parada do scheduler."""
        if not self._running:
            return

        try:
            self._scheduler.stop()
        finally:
            self._running = False

    def run_forever(self) -> None:
        """Inicia o monitor e mantém o processo ativo.

        O Runtime não implementa temporização própria. A execução
        periódica continua sendo responsabilidade do scheduler.
        """
        self.start()

        try:
            self._wait_forever()
        finally:
            self.stop()

    def _wait_forever(self) -> None:
        """Mantém o processo ativo até que o Runtime seja interrompido."""
        import threading

        threading.Event().wait()
