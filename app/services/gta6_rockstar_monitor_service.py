from __future__ import annotations

from app.integrations.gta6.rockstar_news import ROCKSTAR_NEWSWIRE_URL
from app.integrations.gta6.vice_monitor import GTA6ViceMonitor
from app.services.gta6_monitor_persistence_service import (
    GTA6PersistentMonitorResult,
    monitor_gta6_page_persisted,
)
from app.integrations.gta6.vice_monitor import MonitoredPage
from app.services.gta6_change_detector import detect_content_change


def monitor_rockstar_newswire(
    *,
    timeout: float = 15.0,
    acquired_source: dict | None = None,
) -> GTA6PersistentMonitorResult:
    """Monitora a página oficial do Rockstar Newswire."""

    if isinstance(acquired_source, dict):
        content = str(acquired_source.get("content") or "")
        provenance = dict(acquired_source.get("provenance") or {})
        if (
            acquired_source.get("status") != "EXECUTED"
            or not content.strip()
            or provenance.get("source_url") != ROCKSTAR_NEWSWIRE_URL
        ):
            raise RuntimeError("governed Rockstar acquisition is incomplete")
        change = detect_content_change(content, None)
        return GTA6PersistentMonitorResult(
            url=ROCKSTAR_NEWSWIRE_URL,
            status_code=200,
            content=content,
            change=change,
            baseline=True,
        )

    monitor = GTA6ViceMonitor(timeout=timeout)
    return monitor_gta6_page_persisted(monitor, ROCKSTAR_NEWSWIRE_URL)
