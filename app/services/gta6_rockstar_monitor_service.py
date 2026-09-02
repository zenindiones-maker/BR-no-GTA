from __future__ import annotations

from app.integrations.gta6.rockstar_news import ROCKSTAR_NEWSWIRE_URL
from app.integrations.gta6.vice_monitor import GTA6ViceMonitor
from app.services.gta6_monitor_persistence_service import (
    GTA6PersistentMonitorResult,
    monitor_gta6_page_persisted,
)


def monitor_rockstar_newswire(
    *,
    timeout: float = 15.0,
) -> GTA6PersistentMonitorResult:
    """Monitora a página oficial do Rockstar Newswire."""

    monitor = GTA6ViceMonitor(timeout=timeout)

    return monitor_gta6_page_persisted(
        monitor,
        ROCKSTAR_NEWSWIRE_URL,
    )
