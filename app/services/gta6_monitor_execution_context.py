from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class GTA6MonitorExecutionContext:
    execution_id: str
    job_id: str
    run_id: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.execution_id, str)
            or not self.execution_id.strip()
        ):
            raise ValueError(
                "execution_id must be a non-empty string"
            )

        if (
            not isinstance(self.job_id, str)
            or not self.job_id.strip()
        ):
            raise ValueError(
                "job_id must be a non-empty string"
            )

        if (
            not isinstance(self.run_id, int)
            or isinstance(self.run_id, bool)
            or self.run_id <= 0
        ):
            raise ValueError(
                "run_id must be a positive integer"
            )

    @classmethod
    def create(
        cls,
        *,
        job_id: str,
        run_id: int,
    ) -> "GTA6MonitorExecutionContext":
        return cls(
            execution_id=str(uuid4()),
            job_id=job_id,
            run_id=run_id,
        )
