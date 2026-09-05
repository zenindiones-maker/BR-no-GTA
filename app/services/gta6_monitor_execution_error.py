from __future__ import annotations

from app.services.gta6_monitor_execution_context import (
    GTA6MonitorExecutionContext,
)


class GTA6MonitorExecutionError(Exception):
    def __init__(
        self,
        *,
        context: GTA6MonitorExecutionContext,
        cause: BaseException,
    ) -> None:
        if not isinstance(
            context,
            GTA6MonitorExecutionContext,
        ):
            raise ValueError("context must be provided")

        if cause is None:
            raise ValueError("cause must be provided")

        self._context = context
        self._cause = cause

        super().__init__(str(cause))

    @property
    def context(self) -> GTA6MonitorExecutionContext:
        return self._context

    @property
    def cause(self) -> BaseException:
        return self._cause

    @property
    def execution_id(self) -> str:
        return self._context.execution_id

    @property
    def run_id(self) -> int:
        return self._context.run_id

    @property
    def job_id(self) -> str:
        return self._context.job_id
