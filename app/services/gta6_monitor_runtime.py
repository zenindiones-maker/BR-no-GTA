from __future__ import annotations

import signal
from types import FrameType
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
        self._previous_signal_handlers: dict[
            int,
            Any,
        ] = {}
        self._signals_installed = False

    @property
    def scheduler(self) -> Any:
        return self._scheduler

    @property
    def running(self) -> bool:
        """Indica se o Runtime está atualmente em execução."""
        return self._running

    def install_signal_handlers(self) -> None:
        """Registra handlers para encerramento gracioso do processo."""
        if self._signals_installed:
            return

        self._previous_signal_handlers = {
            signal.SIGINT: signal.signal(
                signal.SIGINT,
                self._handle_shutdown_signal,
            ),
            signal.SIGTERM: signal.signal(
                signal.SIGTERM,
                self._handle_shutdown_signal,
            ),
        }

        self._signals_installed = True

    def restore_signal_handlers(self) -> None:
        """Restaura os handlers de sinais anteriores."""
        if not self._signals_installed:
            return

        for signum, handler in self._previous_signal_handlers.items():
            signal.signal(
                signum,
                handler,
            )

        self._previous_signal_handlers = {}
        self._signals_installed = False

    def _handle_shutdown_signal(
        self,
        signum: int,
        frame: FrameType | None,
    ) -> None:
        """Solicita o encerramento gracioso do Runtime."""
        self.stop()

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
        self.install_signal_handlers()

        try:
            self.start()
            self._wait_forever()
        finally:
            self.stop()
            self.restore_signal_handlers()

    def _wait_forever(self) -> None:
        """Mantém o processo ativo até que o Runtime seja interrompido."""
        import threading

        threading.Event().wait()
