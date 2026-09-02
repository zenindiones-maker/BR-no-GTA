from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GTA6MonitorEvent:
    url: str
    previous_hash: str | None
    current_hash: str
    detected_at: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url.strip():
            raise ValueError("url must be a non-empty string")

        if self.previous_hash is not None:
            if (
                not isinstance(self.previous_hash, str)
                or not self.previous_hash.strip()
            ):
                raise ValueError(
                    "previous_hash must be a non-empty string or None"
                )

        if (
            not isinstance(self.current_hash, str)
            or not self.current_hash.strip()
        ):
            raise ValueError(
                "current_hash must be a non-empty string"
            )

        if self.detected_at is not None:
            if (
                not isinstance(self.detected_at, str)
                or not self.detected_at.strip()
            ):
                raise ValueError(
                    "detected_at must be a non-empty string or None"
                )


def create_gta6_monitor_event(
    url: str,
    previous_hash: str | None,
    current_hash: str,
    detected_at: str | None = None,
) -> GTA6MonitorEvent:
    return GTA6MonitorEvent(
        url=url.strip(),
        previous_hash=(
            previous_hash.strip()
            if previous_hash is not None
            else None
        ),
        current_hash=current_hash.strip(),
        detected_at=(
            detected_at.strip()
            if detected_at is not None
            else None
        ),
    )
