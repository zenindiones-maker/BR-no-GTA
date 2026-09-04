from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GTA6MonitorSchedule:
    """Contrato imutável para o agendamento do monitor GTA6."""

    interval_seconds: float = 300.0
    timeout: float = 15.0
    misfire_grace_time: int = 60
    enabled: bool = True
    job_id: str = "gta6-monitor"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.interval_seconds, (int, float))
            or isinstance(self.interval_seconds, bool)
            or self.interval_seconds <= 0
        ):
            raise ValueError(
                "interval_seconds must be a positive number"
            )

        if (
            not isinstance(self.timeout, (int, float))
            or isinstance(self.timeout, bool)
            or self.timeout <= 0
        ):
            raise ValueError(
                "timeout must be a positive number"
            )

        if (
            not isinstance(self.misfire_grace_time, int)
            or isinstance(self.misfire_grace_time, bool)
            or self.misfire_grace_time <= 0
        ):
            raise ValueError(
                "misfire_grace_time must be a positive integer"
            )

        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")

        if not isinstance(self.job_id, str) or not self.job_id.strip():
            raise ValueError("job_id must be a non-empty string")
