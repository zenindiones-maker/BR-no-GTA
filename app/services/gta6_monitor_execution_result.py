from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.gta6_monitor_execution_context import (
    GTA6MonitorExecutionContext,
)


@dataclass(frozen=True)
class GTA6MonitorExecutionResult:
    context: GTA6MonitorExecutionContext
    result: Any

    def __post_init__(self) -> None:
        if not isinstance(
            self.context,
            GTA6MonitorExecutionContext,
        ):
            raise ValueError("context must be provided")

        if self.result is None:
            raise ValueError("result must be provided")

    @property
    def execution_id(self) -> str:
        return self.context.execution_id

    @property
    def run_id(self) -> int:
        return self.context.run_id
