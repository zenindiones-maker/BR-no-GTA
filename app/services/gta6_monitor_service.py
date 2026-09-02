from __future__ import annotations

from dataclasses import dataclass

from app.integrations.gta6.vice_monitor import GTA6ViceMonitor
from app.services.gta6_change_detector import (
    GTA6ChangeResult,
    detect_content_change,
)


@dataclass(frozen=True)
class GTA6MonitorResult:
    url: str
    status_code: int
    change: GTA6ChangeResult


def monitor_gta6_page(
    monitor: GTA6ViceMonitor,
    url: str,
    previous_hash: str | None,
) -> GTA6MonitorResult:
    """Executa coleta HTTP e compara o conteúdo observado."""

    if not isinstance(monitor, GTA6ViceMonitor):
        raise ValueError(
            "monitor must be a GTA6ViceMonitor"
        )

    page = monitor.fetch(url)

    change = detect_content_change(
        page.content,
        previous_hash,
    )

    return GTA6MonitorResult(
        url=page.url,
        status_code=page.status_code,
        change=change,
    )
